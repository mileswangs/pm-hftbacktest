import type { EntryHourSummary, WeatherDataset, WeatherEvent, WeatherOutcome, WeatherRun } from './types';
import { fmtPct } from '../lib/format';
import { CHART, COMPARE_COLORS } from '../theme/colors';

export type OutcomeResearchRow = {
  outcome: WeatherOutcome;
  entryProb: number | null;
  selected: boolean;
  staleMinutes: number | null;
  updates6h: number;
  move6hBeforeEntry: number | null;
  move1hAfterEntry: number | null;
};

export type EventBacktestRow = {
  eventSlug: string;
  date: string;
  winnerLabel: string | null;
  entryHours: number;
  pnl: number;
  cumulativePnl: number;
  didHit: boolean;
  selectedLabels: string[];
  selectedProbabilitySum: number;
  selectionMode: string;
  reason: string;
};

export type ExecutionPolicy = {
  slippagePerLeg: number;
  feePerLeg: number;
  maxStaleMinutes: number;
  minUpdates6h: number;
};

export type StrategyPolicy = ExecutionPolicy & {
  maxProbabilitySum: number;
  minSignalMargin: number;
  maxPreEntryMove6h: number;
  requireAdjacentPair: boolean;
};

export type StrategyDecision = {
  verdict: 'trade' | 'watch' | 'skip';
  headline: string;
  reasons: string[];
  warnings: string[];
  selectedCount: number;
  thresholdMargin: number | null;
  headroomToMaxCost: number | null;
  avgStaleMinutes: number | null;
  avgUpdates6h: number | null;
  avgMove6hBeforeEntry: number | null;
  pairAdjacent: boolean;
  gatedPnl: number;
};

export type StrategyHourSummary = {
  entryHours: number;
  rawTradeCount: number;
  tradeCount: number;
  watchCount: number;
  skipCount: number;
  gatedHitRate: number;
  gatedTotalPnl: number;
};

export type StrategyEventRow = {
  eventSlug: string;
  date: string;
  verdict: StrategyDecision['verdict'];
  headline: string;
  gatedPnl: number;
  cumulativeGatedPnl: number;
  selectedLabels: string[];
  blockReasons: string[];
};

export type ExecutionEventRow = {
  eventSlug: string;
  date: string;
  rawPnl: number;
  conservativePnl: number;
  cumulativeRawPnl: number;
  cumulativeConservativePnl: number;
  selectedProbabilitySum: number;
  conservativeCost: number;
  didHit: boolean;
  selectedLabels: string[];
  blockedByPolicy: boolean;
  blockReasons: string[];
  entryTimestamp: number;
  endTimestamp: number;
};

export type NearLockBoardRow = {
  outcome: WeatherOutcome;
  labelKey: number | null;
  entryProb: number | null;
  staleMinutes: number | null;
  updates6h: number;
  spread: number | null;
  edgeToSettlement: number | null;
  selected: boolean;
  isWinner: boolean;
  verdict: 'trade' | 'watch' | 'avoid';
  note: string;
};

export type DailyBuyPointRow = {
  date: string;
  entryTimeEdt: string;
  selection: string;
  probabilityPaid: number;
  pnl: number;
  didHit: boolean;
  winnerLabel: string | null;
};

export const ORDERBOOK_CAPACITY_URLS: Record<string, Partial<Record<number, string>>> = {
  madrid: {
    36: '/data/weather/madrid-pmxt-orderbook-36h.json',
  },
};

export function outcomeColor(
  outcome: WeatherOutcome,
  selectedIndex: number,
  topCandidateLabels: Set<string>,
): { color: string; opacity?: number; dashed?: boolean } {
  if (selectedIndex >= 0) {
    return { color: COMPARE_COLORS[selectedIndex % COMPARE_COLORS.length] };
  }
  if (outcome.isWinner) {
    return { color: CHART.position };
  }
  if (topCandidateLabels.has(outcome.label)) {
    return { color: '#9a6b1f', opacity: 0.78 };
  }
  return { color: CHART.price, opacity: 0.28, dashed: true };
}

export function toneForPnl(value: number): string {
  if (value > 0) {
    return `rgba(79, 122, 46, ${Math.min(0.65, 0.18 + Math.abs(value) * 0.5)})`;
  }
  if (value < 0) {
    return `rgba(178, 58, 46, ${Math.min(0.65, 0.18 + Math.abs(value) * 0.5)})`;
  }
  return 'rgba(122, 105, 81, 0.12)';
}

export function sumSummary(summary: EntryHourSummary[]) {
  const totalTrades = summary.reduce((acc, item) => acc + item.tradedCount, 0);
  const totalPnl = summary.reduce((acc, item) => acc + item.totalPnl, 0);
  return { totalTrades, totalPnl };
}

export function findRun(event: WeatherEvent | null, entryHours: number | null): WeatherRun | null {
  if (!event || entryHours == null) return null;
  return event.runs.find((run) => run.entryHours === entryHours) ?? null;
}

export function average(values: Array<number | null | undefined>): number | null {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (usable.length === 0) return null;
  return usable.reduce((acc, value) => acc + value, 0) / usable.length;
}

export function sumNullable(values: Array<number | null | undefined>): number | null {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (usable.length === 0) return null;
  return usable.reduce((acc, value) => acc + value, 0);
}

export function minNullable(values: Array<number | null | undefined>): number | null {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (usable.length === 0) return null;
  return Math.min(...usable);
}

export function medianNullable(values: Array<number | null | undefined>): number | null {
  const usable = values
    .filter((value): value is number => value != null && Number.isFinite(value))
    .sort((a, b) => a - b);
  if (usable.length === 0) return null;
  const mid = Math.floor(usable.length / 2);
  return usable.length % 2 === 0 ? (usable[mid - 1] + usable[mid]) / 2 : usable[mid];
}

export function fmtCompact(value: number | null, digits = 2): string {
  if (value == null) return '-';
  return value.toLocaleString('en-US', {
    notation: Math.abs(value) >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: digits,
  });
}

export function fmtMaybe(value: number | null, digits = 3): string {
  if (value == null) return '-';
  return value.toFixed(digits);
}

export function fmtEdtTimestamp(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  })
    .format(date)
    .replace(',', '')
    .replace(/\//g, '-')
    .replace(' AM', ' AM EDT')
    .replace(' PM', ' PM EDT');
}

export function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function bucketKey(label: string): number | null {
  const matches = [...label.matchAll(/-?\d+/g)].map((match) => Number(match[0]));
  if (matches.length === 0) return null;
  if (matches.length >= 2) {
    return (matches[0] + matches[1]) / 2;
  }
  return matches[0];
}

export function lastPointAtOrBefore(outcome: WeatherOutcome, ts: number) {
  let answer: { t: number; p: number } | null = null;
  for (const point of outcome.points) {
    if (point.t > ts) break;
    answer = point;
  }
  return answer;
}

export function firstPointAfter(outcome: WeatherOutcome, ts: number) {
  for (const point of outcome.points) {
    if (point.t > ts) return point;
  }
  return null;
}

export function countUpdatesWithin(outcome: WeatherOutcome, startTs: number, endTs: number) {
  let count = 0;
  for (const point of outcome.points) {
    if (point.t < startTs) continue;
    if (point.t > endTs) break;
    count += 1;
  }
  return count;
}

export function maxAbsMoveAfter(outcome: WeatherOutcome, entryTs: number, horizonMs: number) {
  const entryPoint = lastPointAtOrBefore(outcome, entryTs);
  if (!entryPoint) return null;
  let maxMove = 0;
  let seen = false;
  const endTs = entryTs + horizonMs;
  for (const point of outcome.points) {
    if (point.t < entryTs) continue;
    if (point.t > endTs) break;
    seen = true;
    maxMove = Math.max(maxMove, Math.abs(point.p - entryPoint.p));
  }
  return seen ? maxMove : null;
}

export function maxAbsMoveWithin(outcome: WeatherOutcome, startTs: number, endTs: number) {
  let basePoint: { t: number; p: number } | null = null;
  let maxMove = 0;
  let seen = false;
  for (const point of outcome.points) {
    if (point.t < startTs) continue;
    if (point.t > endTs) break;
    if (basePoint == null) {
      basePoint = point;
      continue;
    }
    seen = true;
    maxMove = Math.max(maxMove, Math.abs(point.p - basePoint.p));
  }
  return seen ? maxMove : null;
}

export function areSelectedBucketsAdjacent(selectedEvent: WeatherEvent | null, labels: string[]) {
  if (!selectedEvent || labels.length <= 1) return true;
  const indices = labels
    .map((label) => selectedEvent.outcomes.findIndex((outcome) => outcome.label === label))
    .filter((index) => index >= 0)
    .sort((a, b) => a - b);
  if (indices.length <= 1) return true;
  return indices[indices.length - 1] - indices[0] === indices.length - 1;
}

export function thresholdMarginForRun(selectedRun: WeatherRun | null, threshold: number) {
  if (!selectedRun || selectedRun.selectedLabels.length === 0) return null;
  if (selectedRun.selectedLabels.length === 1) {
    return (selectedRun.selectedPrices[0] ?? 0) - threshold;
  }
  return selectedRun.selectedProbabilitySum - threshold;
}

export function buildNearLockRows(
  selectedRun: WeatherRun | null,
  researchRows: OutcomeResearchRow[],
  policy: ExecutionPolicy,
): NearLockBoardRow[] {
  if (!selectedRun) return [];
  return researchRows
    .map((row) => {
      const entryProb = row.entryProb;
      const edgeToSettlement = entryProb == null ? null : (row.outcome.isWinner ? 1 : 0) - entryProb;
      const staleOk = row.staleMinutes != null && row.staleMinutes <= policy.maxStaleMinutes;
      const updatesOk = row.updates6h >= policy.minUpdates6h;
      const spreadOk = row.outcome.marketStats.spread == null || row.outcome.marketStats.spread <= 8;
      const underpriced = entryProb != null && entryProb <= 0.82;

      let verdict: NearLockBoardRow['verdict'] = 'avoid';
      if (staleOk && updatesOk && spreadOk && underpriced && edgeToSettlement != null && edgeToSettlement >= 0.08) {
        verdict = 'trade';
      } else if (staleOk && updatesOk) {
        verdict = 'watch';
      }

      const note = !staleOk
        ? 'feed stale'
        : !updatesOk
          ? 'too few prints'
          : !spreadOk
            ? 'spread wide'
            : !underpriced
              ? 'price already rich'
              : edgeToSettlement != null && edgeToSettlement >= 0.08
                ? 'lag still open'
                : 'thin edge';

      return {
        outcome: row.outcome,
        labelKey: bucketKey(row.outcome.label),
        entryProb,
        staleMinutes: row.staleMinutes,
        updates6h: row.updates6h,
        spread: row.outcome.marketStats.spread,
        edgeToSettlement,
        selected: row.selected,
        isWinner: row.outcome.isWinner,
        verdict,
        note,
      };
    })
    .sort((a, b) => {
      if (a.selected !== b.selected) return a.selected ? -1 : 1;
      if (a.verdict !== b.verdict) return a.verdict === 'trade' ? -1 : a.verdict === 'watch' ? -1 : 1;
      return (b.edgeToSettlement ?? -999) - (a.edgeToSettlement ?? -999) || (a.labelKey ?? 0) - (b.labelKey ?? 0);
    });
}

export function buildAlphaNotes(dataset: WeatherDataset | null): string[] {
  if (!dataset || dataset.summaryByEntryHour.length === 0) return [];
  const ranked = [...dataset.summaryByEntryHour].sort((a, b) => b.totalPnl - a.totalPnl);
  const best = ranked[0];
  const second = ranked[1] ?? null;
  const notes: string[] = [];

  if (best.totalPnl > 0) {
    notes.push(
      `${dataset.cityLabel} currently backtests best at ${best.entryHours}h, with ${best.tradedCount} trades, ${fmtPct(best.hitRate, 1)} hit rate, and total PnL ${best.totalPnl.toFixed(3)}.`,
    );
  } else {
    notes.push(
      `${dataset.cityLabel} has no positive entry hour in this window. Treat it as a weak alpha candidate unless the sampling window or rule changes.`,
    );
  }

  if (second) {
    const gap = best.totalPnl - second.totalPnl;
    if (Math.abs(gap) >= 1) {
      notes.push(
        `Entry timing is sensitive here: the gap between the best hour (${best.entryHours}h) and runner-up (${second.entryHours}h) is ${gap.toFixed(3)} PnL.`,
      );
    } else {
      notes.push(`The best two entry hours are relatively close, so this city looks less timing-fragile than Chengdu-style one-hour sweet spots.`);
    }
  }

  const pairRatio = best.tradedCount > 0 ? best.pairCount / best.tradedCount : 0;
  if (pairRatio > 0.5) {
    notes.push('Most winning trades come from buying two adjacent temperature buckets, so size should be cut for slippage and execution complexity.');
  } else if (best.singleCount > 0) {
    notes.push('Single-bucket entries dominate the best hour, which is cleaner operationally and usually easier to size.');
  }

  return notes.slice(0, 3);
}

export function buildEventBacktestRows(dataset: WeatherDataset | null, entryHours: number | null): EventBacktestRow[] {
  if (!dataset || entryHours == null) return [];
  let cumulative = 0;
  return dataset.events
    .map((event) => {
      const run = findRun(event, entryHours);
      if (!run) return null;
      cumulative += run.pnl;
      return {
        eventSlug: event.eventSlug,
        date: event.date,
        winnerLabel: event.winnerLabel,
        entryHours: run.entryHours,
        pnl: run.pnl,
        cumulativePnl: cumulative,
        didHit: run.didHit,
        selectedLabels: run.selectedLabels,
        selectedProbabilitySum: run.selectedProbabilitySum,
        selectionMode: run.selectionMode,
        reason: run.reason,
      };
    })
    .filter((row): row is EventBacktestRow => row != null);
}

export function buildResearchRowsForRun(selectedEvent: WeatherEvent | null, selectedRun: WeatherRun | null): OutcomeResearchRow[] {
  if (!selectedEvent || !selectedRun) return [];
  return selectedEvent.outcomes
    .map((outcome) => {
      const directIdx = selectedRun.selectedLabels.indexOf(outcome.label);
      const lastPoint = lastPointAtOrBefore(outcome, selectedRun.entryTimestamp);
      return {
        outcome,
        entryProb: directIdx >= 0 ? selectedRun.selectedPrices[directIdx] ?? null : lastPoint?.p ?? null,
        selected: directIdx >= 0,
        staleMinutes: lastPoint ? (selectedRun.entryTimestamp - lastPoint.t) / 60000 : null,
        updates6h: countUpdatesWithin(outcome, selectedRun.entryTimestamp - 6 * 60 * 60 * 1000, selectedRun.entryTimestamp),
        move6hBeforeEntry: maxAbsMoveWithin(
          outcome,
          selectedRun.entryTimestamp - 6 * 60 * 60 * 1000,
          selectedRun.entryTimestamp,
        ),
        move1hAfterEntry: maxAbsMoveAfter(outcome, selectedRun.entryTimestamp, 60 * 60 * 1000),
      };
    })
    .sort((a, b) => (b.entryProb ?? -1) - (a.entryProb ?? -1));
}

export function buildStrategyDecision(
  selectedEvent: WeatherEvent | null,
  selectedRun: WeatherRun | null,
  researchRows: OutcomeResearchRow[],
  threshold: number,
  policy: StrategyPolicy,
): StrategyDecision {
  if (!selectedRun || !selectedEvent) {
    return {
      verdict: 'skip',
      headline: 'No active setup',
      reasons: ['No selected run is loaded.'],
      warnings: [],
      selectedCount: 0,
      thresholdMargin: null,
      headroomToMaxCost: null,
      avgStaleMinutes: null,
      avgUpdates6h: null,
      avgMove6hBeforeEntry: null,
      pairAdjacent: true,
      gatedPnl: 0,
    };
  }

  const selectedRows = researchRows.filter((row) => row.selected);
  if (selectedRows.length === 0) {
    return {
      verdict: 'skip',
      headline: 'No buy signal',
      reasons: ['This run never crossed the entry rule, so there is nothing to execute.'],
      warnings: [],
      selectedCount: 0,
      thresholdMargin: null,
      headroomToMaxCost: null,
      avgStaleMinutes: null,
      avgUpdates6h: null,
      avgMove6hBeforeEntry: null,
      pairAdjacent: true,
      gatedPnl: 0,
    };
  }

  const thresholdMargin = thresholdMarginForRun(selectedRun, threshold);
  const headroomToMaxCost = policy.maxProbabilitySum - selectedRun.selectedProbabilitySum;
  const avgStaleMinutes = average(selectedRows.map((row) => row.staleMinutes));
  const avgUpdates6h = average(selectedRows.map((row) => row.updates6h));
  const avgMove6hBeforeEntry = average(selectedRows.map((row) => row.move6hBeforeEntry));
  const pairAdjacent = areSelectedBucketsAdjacent(selectedEvent, selectedRun.selectedLabels);
  const reasons: string[] = [];
  const warnings: string[] = [];

  if (selectedRun.selectedLabels.length >= 2 && policy.requireAdjacentPair && !pairAdjacent) {
    reasons.push('selected pair is not adjacent on the temperature ladder');
  }
  if (thresholdMargin == null || thresholdMargin < policy.minSignalMargin) {
    reasons.push(`signal margin ${fmtPct(thresholdMargin ?? 0, 1)} is below the ${fmtPct(policy.minSignalMargin, 0)} guardrail`);
  }
  if (selectedRun.selectedProbabilitySum > policy.maxProbabilitySum) {
    reasons.push(
      `paid ${fmtPct(selectedRun.selectedProbabilitySum, 1)}, above the ${fmtPct(policy.maxProbabilitySum, 0)} max-cost guardrail`,
    );
  }
  if (selectedRows.some((row) => row.staleMinutes == null || row.staleMinutes > policy.maxStaleMinutes)) {
    reasons.push(`one or more selected buckets were stale beyond ${policy.maxStaleMinutes}m`);
  }
  if (selectedRows.some((row) => row.updates6h < policy.minUpdates6h)) {
    reasons.push(`one or more selected buckets had fewer than ${policy.minUpdates6h} updates in the last 6h`);
  }
  if (avgMove6hBeforeEntry != null && avgMove6hBeforeEntry > policy.maxPreEntryMove6h) {
    reasons.push(
      `pre-entry 6h move ${fmtPct(avgMove6hBeforeEntry, 1)} exceeded the ${fmtPct(policy.maxPreEntryMove6h, 0)} volatility cap`,
    );
  }

  if (reasons.length === 0) {
    if (headroomToMaxCost != null && headroomToMaxCost < 0.03) {
      warnings.push(`only ${fmtPct(headroomToMaxCost, 1)} headroom remained before max cost`);
    }
    if (thresholdMargin != null && thresholdMargin < policy.minSignalMargin * 1.6) {
      warnings.push('signal only barely cleared the threshold');
    }
    if (avgStaleMinutes != null && avgStaleMinutes > policy.maxStaleMinutes * 0.7) {
      warnings.push('feed freshness was acceptable but not clean');
    }
    if (avgMove6hBeforeEntry != null && avgMove6hBeforeEntry > policy.maxPreEntryMove6h * 0.7) {
      warnings.push('market was already repricing quickly before entry');
    }
  }

  const verdict: StrategyDecision['verdict'] = reasons.length > 0 ? 'skip' : warnings.length > 0 ? 'watch' : 'trade';
  const headline =
    verdict === 'trade'
      ? 'Buyable under the current guardrails'
      : verdict === 'watch'
        ? 'Tradable, but only with reduced conviction'
        : 'Skip under the current guardrails';

  return {
    verdict,
    headline,
    reasons,
    warnings,
    selectedCount: selectedRows.length,
    thresholdMargin,
    headroomToMaxCost,
    avgStaleMinutes,
    avgUpdates6h,
    avgMove6hBeforeEntry,
    pairAdjacent,
    gatedPnl: verdict === 'trade' ? selectedRun.pnl : 0,
  };
}

export function buildStrategyHourSummaries(dataset: WeatherDataset | null, policy: StrategyPolicy): StrategyHourSummary[] {
  if (!dataset) return [];
  return dataset.entryHours.map((entryHours) => {
    let tradeCount = 0;
    let watchCount = 0;
    let skipCount = 0;
    let hitCount = 0;
    let gatedTotalPnl = 0;
    let rawTradeCount = 0;

    for (const event of dataset.events) {
      const run = findRun(event, entryHours);
      if (!run) continue;
      if (run.selectedLabels.length > 0) {
        rawTradeCount += 1;
      }
      const rows = buildResearchRowsForRun(event, run);
      const decision = buildStrategyDecision(event, run, rows, dataset.threshold, policy);
      if (decision.verdict === 'trade') {
        tradeCount += 1;
        gatedTotalPnl += run.pnl;
        if (run.didHit) hitCount += 1;
      } else if (decision.verdict === 'watch') {
        watchCount += 1;
      } else {
        skipCount += 1;
      }
    }

    return {
      entryHours,
      rawTradeCount,
      tradeCount,
      watchCount,
      skipCount,
      gatedHitRate: tradeCount > 0 ? hitCount / tradeCount : 0,
      gatedTotalPnl,
    };
  });
}

export function buildStrategyEventRows(
  dataset: WeatherDataset | null,
  entryHours: number | null,
  policy: StrategyPolicy,
): StrategyEventRow[] {
  if (!dataset || entryHours == null) return [];
  let cumulativeGatedPnl = 0;
  return dataset.events
    .map((event) => {
      const run = findRun(event, entryHours);
      if (!run) return null;
      const rows = buildResearchRowsForRun(event, run);
      const decision = buildStrategyDecision(event, run, rows, dataset.threshold, policy);
      cumulativeGatedPnl += decision.gatedPnl;
      return {
        eventSlug: event.eventSlug,
        date: event.date,
        verdict: decision.verdict,
        headline: decision.headline,
        gatedPnl: decision.gatedPnl,
        cumulativeGatedPnl,
        selectedLabels: run.selectedLabels,
        blockReasons: [...decision.reasons, ...decision.warnings],
      };
    })
    .filter((row): row is StrategyEventRow => row != null);
}

export function buildExecutionRows(
  dataset: WeatherDataset | null,
  entryHours: number | null,
  policy: ExecutionPolicy,
): ExecutionEventRow[] {
  if (!dataset || entryHours == null) return [];
  let cumulativeRawPnl = 0;
  let cumulativeConservativePnl = 0;

  return dataset.events
    .map((event) => {
      const run = findRun(event, entryHours);
      if (!run) return null;

      const researchRows = buildResearchRowsForRun(event, run).filter((row) => row.selected);
      const blockReasons: string[] = [];
      if (run.selectedLabels.length > 0) {
        for (const row of researchRows) {
          if (row.staleMinutes == null || row.staleMinutes > policy.maxStaleMinutes) {
            blockReasons.push(`${row.outcome.label} stale ${fmtMaybe(row.staleMinutes, 1)}m`);
          }
          if (row.updates6h < policy.minUpdates6h) {
            blockReasons.push(`${row.outcome.label} updates6h=${row.updates6h}`);
          }
        }
      }

      const blockedByPolicy = run.selectedLabels.length > 0 && blockReasons.length > 0;
      const legs = run.selectedLabels.length;
      const friction = legs * (policy.slippagePerLeg + policy.feePerLeg);
      const conservativeCost = run.selectedProbabilitySum + friction;
      const conservativePnl =
        run.selectedLabels.length === 0 || blockedByPolicy
          ? 0
          : (run.didHit ? 1 : 0) - conservativeCost;

      cumulativeRawPnl += run.pnl;
      cumulativeConservativePnl += conservativePnl;

      return {
        eventSlug: event.eventSlug,
        date: event.date,
        rawPnl: run.pnl,
        conservativePnl,
        cumulativeRawPnl,
        cumulativeConservativePnl,
        selectedProbabilitySum: run.selectedProbabilitySum,
        conservativeCost,
        didHit: run.didHit,
        selectedLabels: run.selectedLabels,
        blockedByPolicy,
        blockReasons,
        entryTimestamp: run.entryTimestamp,
        endTimestamp: new Date(event.endTimeUtc).getTime(),
      };
    })
    .filter((row): row is ExecutionEventRow => row != null);
}

export function buildDailyBuyPointRows(dataset: WeatherDataset | null, entryHours: number): DailyBuyPointRow[] {
  if (!dataset) return [];
  return dataset.events
    .map((event) => {
      const run = findRun(event, entryHours);
      if (!run || run.selectedLabels.length === 0) return null;
      return {
        date: event.date,
        entryTimeEdt: fmtEdtTimestamp(run.entryTimeUtc),
        selection: run.selectedLabels.join(' + '),
        probabilityPaid: run.selectedProbabilitySum,
        pnl: run.pnl,
        didHit: run.didHit,
        winnerLabel: event.winnerLabel,
      };
    })
    .filter((row): row is DailyBuyPointRow => row != null);
}

export function computeMaxDrawdown(rows: ExecutionEventRow[], key: 'cumulativeRawPnl' | 'cumulativeConservativePnl'): number {
  let peak = 0;
  let maxDrawdown = 0;
  for (const row of rows) {
    peak = Math.max(peak, row[key]);
    maxDrawdown = Math.max(maxDrawdown, peak - row[key]);
  }
  return maxDrawdown;
}

export function computeMaxConcurrentCapital(rows: ExecutionEventRow[]): number {
  const events: Array<{ ts: number; delta: number }> = [];
  for (const row of rows) {
    if (row.selectedLabels.length === 0 || row.blockedByPolicy) continue;
    events.push({ ts: row.entryTimestamp, delta: row.conservativeCost });
    events.push({ ts: row.endTimestamp, delta: -row.conservativeCost });
  }
  events.sort((a, b) => a.ts - b.ts || a.delta - b.delta);
  let current = 0;
  let max = 0;
  for (const event of events) {
    current += event.delta;
    max = Math.max(max, current);
  }
  return max;
}


