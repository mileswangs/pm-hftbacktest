import { useEffect, useMemo, useState } from 'react';
import { LineChart } from '../charts/LineChart';
import type { ChartMarker, ChartRule, ChartSeries } from '../charts/LineChart';
import { TopBar } from '../components/TopBar';
import type { AppMode } from '../components/TopBar';
import { fmtDateShort, fmtDateTime, fmtPct } from '../lib/format';
import { CHART, COMPARE_COLORS } from '../theme/colors';
import { buildWeatherDataset, inferCityLabel, parseEntryHours } from '../weather/buildDataset';
import { CITY_PRESETS, CUSTOM_CITY_VALUE, findPresetCity } from '../weather/cityCatalog';
import type {
  EntryHourSummary,
  WeatherDataset,
  WeatherEvent,
  WeatherLibraryManifest,
  WeatherOutcome,
  WeatherRun,
} from '../weather/types';
import './Dashboard.css';
import './WeatherResearchPage.css';

const LEGACY_DATA_URL = '/data/chengdu-weather-backtest.json';
const LIBRARY_MANIFEST_URL = '/data/weather/manifest.json';

type LoadState = 'loading' | 'ready' | 'error';

type OutcomeResearchRow = {
  outcome: WeatherOutcome;
  entryProb: number | null;
  selected: boolean;
  staleMinutes: number | null;
  updates6h: number;
  move1hAfterEntry: number | null;
};

function outcomeColor(
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

function toneForPnl(value: number): string {
  if (value > 0) {
    return `rgba(79, 122, 46, ${Math.min(0.65, 0.18 + Math.abs(value) * 0.5)})`;
  }
  if (value < 0) {
    return `rgba(178, 58, 46, ${Math.min(0.65, 0.18 + Math.abs(value) * 0.5)})`;
  }
  return 'rgba(122, 105, 81, 0.12)';
}

function sumSummary(summary: EntryHourSummary[]) {
  const totalTrades = summary.reduce((acc, item) => acc + item.tradedCount, 0);
  const totalPnl = summary.reduce((acc, item) => acc + item.totalPnl, 0);
  return { totalTrades, totalPnl };
}

function findRun(event: WeatherEvent | null, entryHours: number | null): WeatherRun | null {
  if (!event || entryHours == null) return null;
  return event.runs.find((run) => run.entryHours === entryHours) ?? null;
}

function average(values: Array<number | null | undefined>): number | null {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (usable.length === 0) return null;
  return usable.reduce((acc, value) => acc + value, 0) / usable.length;
}

function sumNullable(values: Array<number | null | undefined>): number | null {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (usable.length === 0) return null;
  return usable.reduce((acc, value) => acc + value, 0);
}

function minNullable(values: Array<number | null | undefined>): number | null {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (usable.length === 0) return null;
  return Math.min(...usable);
}

function medianNullable(values: Array<number | null | undefined>): number | null {
  const usable = values
    .filter((value): value is number => value != null && Number.isFinite(value))
    .sort((a, b) => a - b);
  if (usable.length === 0) return null;
  const mid = Math.floor(usable.length / 2);
  return usable.length % 2 === 0 ? (usable[mid - 1] + usable[mid]) / 2 : usable[mid];
}

function fmtCompact(value: number | null, digits = 2): string {
  if (value == null) return '-';
  return value.toLocaleString('en-US', {
    notation: Math.abs(value) >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: digits,
  });
}

function fmtMaybe(value: number | null, digits = 3): string {
  if (value == null) return '-';
  return value.toFixed(digits);
}

function lastPointAtOrBefore(outcome: WeatherOutcome, ts: number) {
  let answer: { t: number; p: number } | null = null;
  for (const point of outcome.points) {
    if (point.t > ts) break;
    answer = point;
  }
  return answer;
}

function firstPointAfter(outcome: WeatherOutcome, ts: number) {
  for (const point of outcome.points) {
    if (point.t > ts) return point;
  }
  return null;
}

function countUpdatesWithin(outcome: WeatherOutcome, startTs: number, endTs: number) {
  let count = 0;
  for (const point of outcome.points) {
    if (point.t < startTs) continue;
    if (point.t > endTs) break;
    count += 1;
  }
  return count;
}

function maxAbsMoveAfter(outcome: WeatherOutcome, entryTs: number, horizonMs: number) {
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

function buildAlphaNotes(dataset: WeatherDataset | null): string[] {
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

async function loadJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load ${url} (${res.status})`);
  }
  return (await res.json()) as T;
}

export function WeatherResearchPage({
  mode,
  onModeChange,
}: {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
}) {
  const [status, setStatus] = useState<LoadState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [dataset, setDataset] = useState<WeatherDataset | null>(null);
  const [library, setLibrary] = useState<WeatherLibraryManifest | null>(null);
  const [datasetCache, setDatasetCache] = useState<Record<string, WeatherDataset>>({});
  const [progress, setProgress] = useState<string>('');
  const [dataSourceLabel, setDataSourceLabel] = useState<string>('local archive');
  const [selectedEntryHours, setSelectedEntryHours] = useState<number | null>(null);
  const [selectedEventSlug, setSelectedEventSlug] = useState<string | null>(null);
  const [citySlugInput, setCitySlugInput] = useState('chengdu');
  const [cityLabelInput, setCityLabelInput] = useState('Chengdu');
  const [cityPresetValue, setCityPresetValue] = useState('chengdu');
  const [anchorDateInput, setAnchorDateInput] = useState('2026-06-19');
  const [daysInput, setDaysInput] = useState('17');
  const [entryHoursInput, setEntryHoursInput] = useState('6,12,18,24,36');
  const [thresholdInput, setThresholdInput] = useState('0.5');

  function applyDataset(payload: WeatherDataset, sourceLabel: string, progressMessage: string) {
    setDataset(payload);
    setCitySlugInput(payload.citySlug);
    setCityLabelInput(payload.cityLabel);
    setCityPresetValue(findPresetCity(payload.citySlug)?.slug ?? CUSTOM_CITY_VALUE);
    setAnchorDateInput(payload.anchorDate);
    setDaysInput(String(payload.days));
    setEntryHoursInput(payload.entryHours.join(','));
    setThresholdInput(String(payload.threshold));
    setSelectedEntryHours(payload.bestEntryHour ?? payload.entryHours[0] ?? null);
    setSelectedEventSlug(payload.events[payload.events.length - 1]?.eventSlug ?? null);
    setDataSourceLabel(sourceLabel);
    setStatus('ready');
    setProgress(progressMessage);
  }

  async function loadBundledDataset(citySlug: string, explicitPath?: string) {
    if (datasetCache[citySlug]) {
      applyDataset(datasetCache[citySlug], 'local archive', `Loaded local archive for ${datasetCache[citySlug].cityLabel}.`);
      return;
    }

    const manifestEntry = library?.cities.find((entry) => entry.citySlug === citySlug) ?? null;
    const url = explicitPath ?? manifestEntry?.path ?? (citySlug === 'chengdu' ? LEGACY_DATA_URL : '');
    if (!url) {
      throw new Error(`No local dataset archive found for ${citySlug}.`);
    }

    setStatus('loading');
    setError(null);
    setProgress(`Loading local archive for ${citySlug}…`);
    const payload = await loadJson<WeatherDataset>(url);
    setDatasetCache((current) => ({ ...current, [payload.citySlug]: payload }));
    applyDataset(payload, 'local archive', `Loaded local archive for ${payload.cityLabel} (${payload.events.length} resolved event(s)).`);
  }

  async function runInteractiveBuild(next: {
    citySlug: string;
    cityLabel: string;
    anchorDate: string;
    days: number;
    entryHours: number[];
    threshold: number;
  }) {
    setStatus('loading');
    setError(null);
    setProgress('Starting live scan…');
    try {
      const payload = await buildWeatherDataset({
        ...next,
        onProgress: setProgress,
      });
      setDatasetCache((current) => ({ ...current, [payload.citySlug]: payload }));
      applyDataset(payload, 'live API scan', `Scanned ${payload.events.length} resolved event(s) from public APIs.`);
    } catch (err: unknown) {
      setStatus('error');
      setError(err instanceof Error ? err.message : String(err));
      setProgress('');
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setStatus('loading');
      setError(null);
      try {
        const manifest = await loadJson<WeatherLibraryManifest>(LIBRARY_MANIFEST_URL);
        if (cancelled) return;
        setLibrary(manifest);
        const defaultEntry = manifest.cities.find((entry) => entry.citySlug === 'chengdu') ?? manifest.cities[0];
        if (!defaultEntry) {
          throw new Error('Weather library manifest is empty.');
        }
        const payload = await loadJson<WeatherDataset>(defaultEntry.path);
        if (cancelled) return;
        setDatasetCache({ [payload.citySlug]: payload });
        applyDataset(payload, 'local archive', `Loaded local archive for ${payload.cityLabel} (${payload.events.length} resolved event(s)).`);
      } catch (err) {
        if (cancelled) return;
        try {
          const payload = await loadJson<WeatherDataset>(LEGACY_DATA_URL);
          if (cancelled) return;
          setDatasetCache({ [payload.citySlug]: payload });
          applyDataset(payload, 'legacy local sample', `Loaded fallback sample for ${payload.cityLabel}.`);
        } catch (fallbackErr) {
          if (cancelled) return;
          setError(fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr));
          setStatus('error');
        }
      }
    }

    init().catch((err: unknown) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedEvent = useMemo(
    () => dataset?.events.find((event) => event.eventSlug === selectedEventSlug) ?? dataset?.events[dataset.events.length - 1] ?? null,
    [dataset, selectedEventSlug],
  );
  const selectedRun = useMemo(() => findRun(selectedEvent, selectedEntryHours), [selectedEvent, selectedEntryHours]);
  const totals = useMemo(() => sumSummary(dataset?.summaryByEntryHour ?? []), [dataset]);

  const chartSeries = useMemo<ChartSeries[]>(() => {
    if (!selectedEvent || !selectedRun) return [];
    const topCandidateLabels = new Set(selectedRun.topCandidates.map((item) => item.label));
    return selectedEvent.outcomes.map((outcome) => {
      const selectedIndex = selectedRun.selectedLabels.indexOf(outcome.label);
      const style = outcomeColor(outcome, selectedIndex, topCandidateLabels);
      return {
        label: outcome.label,
        color: style.color,
        opacity: style.opacity,
        dashed: style.dashed,
        points: outcome.points.map((point) => ({ x: point.t, y: point.p })),
      };
    });
  }, [selectedEvent, selectedRun]);

  const chartMarkers = useMemo<ChartMarker[]>(() => {
    if (!selectedEvent || !selectedRun) return [];
    return selectedRun.selectedLabels.map((label, index) => ({
      x: selectedRun.entryTimestamp,
      y: selectedRun.selectedPrices[index] ?? 0,
      color: COMPARE_COLORS[index % COMPARE_COLORS.length],
      label: `BUY ${label}`,
    }));
  }, [selectedEvent, selectedRun]);

  const chartRules = useMemo<ChartRule[]>(() => {
    if (!selectedRun) return [];
    return [
      {
        x: selectedRun.entryTimestamp,
        color: CHART.text,
        label: `${selectedRun.entryHours}h entry`,
        dashed: true,
      },
    ];
  }, [selectedRun]);

  const entrySummary = useMemo(
    () => dataset?.summaryByEntryHour.find((item) => item.entryHours === selectedEntryHours) ?? null,
    [dataset, selectedEntryHours],
  );

  const cityBoard = useMemo(
    () => [...(library?.cities ?? [])].sort((a, b) => b.bestTotalPnl - a.bestTotalPnl || a.cityLabel.localeCompare(b.cityLabel)),
    [library],
  );

  const alphaNotes = useMemo(() => buildAlphaNotes(dataset), [dataset]);

  const researchRows = useMemo<OutcomeResearchRow[]>(() => {
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
          move1hAfterEntry: maxAbsMoveAfter(outcome, selectedRun.entryTimestamp, 60 * 60 * 1000),
        };
      })
      .sort((a, b) => (b.entryProb ?? -1) - (a.entryProb ?? -1));
  }, [selectedEvent, selectedRun]);

  const selectedResearchRows = useMemo(() => researchRows.filter((row) => row.selected), [researchRows]);

  const capacitySummary = useMemo(() => {
    const basis = selectedResearchRows.length > 0 ? selectedResearchRows : researchRows.slice(0, 2);
    return {
      selectedVolume: sumNullable(basis.map((row) => row.outcome.marketStats.volume)),
      selectedVolume24hr: sumNullable(basis.map((row) => row.outcome.marketStats.volume24hr)),
      selectedLiquidity: sumNullable(basis.map((row) => row.outcome.marketStats.liquidity)),
      medianSpread: medianNullable(basis.map((row) => row.outcome.marketStats.spread)),
      minOrderSize: minNullable(basis.map((row) => row.outcome.marketStats.orderMinSize)),
      minRewardSize: minNullable(basis.map((row) => row.outcome.marketStats.rewardsMinSize)),
      avgStaleMinutes: average(basis.map((row) => row.staleMinutes)),
      avgUpdates6h: average(basis.map((row) => row.updates6h)),
      avgMove1h: average(basis.map((row) => row.move1hAfterEntry)),
      nextPrintDelayMinutes: average(
        basis.map((row) => {
          const next = firstPointAfter(row.outcome, selectedRun?.entryTimestamp ?? 0);
          return next && selectedRun ? (next.t - selectedRun.entryTimestamp) / 60000 : null;
        }),
      ),
    };
  }, [researchRows, selectedResearchRows, selectedRun]);

  const isCustomCity = cityPresetValue === CUSTOM_CITY_VALUE;
  const selectedPresetHasArchive = useMemo(
    () => !!library?.cities.some((entry) => entry.citySlug === citySlugInput.trim().toLowerCase()),
    [library, citySlugInput],
  );

  function submitGenerator() {
    const citySlug = citySlugInput.trim().toLowerCase();
    const cityLabel = cityLabelInput.trim() || inferCityLabel(citySlug);
    const days = Number(daysInput);
    const threshold = Number(thresholdInput);
    const entryHours = parseEntryHours(entryHoursInput);
    if (!citySlug) {
      setError('City slug is required.');
      setStatus('error');
      return;
    }
    if (!anchorDateInput) {
      setError('Anchor date is required.');
      setStatus('error');
      return;
    }
    if (!Number.isFinite(days) || days <= 0) {
      setError('Days must be a positive number.');
      setStatus('error');
      return;
    }
    if (!Number.isFinite(threshold) || threshold <= 0 || threshold >= 1) {
      setError('Threshold must be between 0 and 1.');
      setStatus('error');
      return;
    }
    if (entryHours.length === 0) {
      setError('Entry hours must contain at least one positive number.');
      setStatus('error');
      return;
    }
    void runInteractiveBuild({
      citySlug,
      cityLabel,
      anchorDate: anchorDateInput,
      days,
      entryHours,
      threshold,
    });
  }

  function handleCityPresetChange(value: string) {
    setCityPresetValue(value);
    if (value === CUSTOM_CITY_VALUE) {
      return;
    }
    const preset = findPresetCity(value);
    if (!preset) return;
    setCitySlugInput(preset.slug);
    setCityLabelInput(preset.label);
    void loadBundledDataset(preset.slug).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
  }

  function handleCitySlugChange(value: string) {
    const nextSlug = value.trim().toLowerCase();
    setCitySlugInput(value);
    const preset = findPresetCity(nextSlug);
    if (!preset) {
      setCityPresetValue(CUSTOM_CITY_VALUE);
      return;
    }
    setCityPresetValue(preset.slug);
    setCityLabelInput(preset.label);
    void loadBundledDataset(preset.slug).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
  }

  return (
    <div className="shell">
      <TopBar mode={mode} onModeChange={onModeChange} adapter="mock" onAdapterChange={() => undefined} />
      <main className="grid">
        <section className="col-history weather-panel weather-list">
          <div className="eyebrow">Dates</div>
          {status === 'loading' ? <p className="muted">Loading weather research workspace…</p> : null}
          {status === 'error' ? <p className="neg mono">{error}</p> : null}
          {status === 'ready' && dataset ? (
            <>
              <div className="weather-overview-card card">
                <div className="eyebrow">Dataset</div>
                <h2>{dataset.cityLabel} Highest Temperature</h2>
                <p className="muted" style={{ margin: '6px 0 0' }}>
                  {dataset.events.length} resolved days, {dataset.entryHours.length} entry points, source: <strong>{dataSourceLabel}</strong>.
                </p>
                <div className="weather-stat-strip">
                  <div>
                    <span className="eyebrow">Anchor</span>
                    <strong>{dataset.anchorDate}</strong>
                  </div>
                  <div>
                    <span className="eyebrow">Trades</span>
                    <strong>{totals.totalTrades}</strong>
                  </div>
                  <div>
                    <span className="eyebrow">Grid PnL</span>
                    <strong className={totals.totalPnl >= 0 ? 'pos' : 'neg'}>{totals.totalPnl.toFixed(3)}</strong>
                  </div>
                </div>
              </div>

              <ul className="weather-event-list">
                {[...dataset.events].reverse().map((event) => {
                  const run = findRun(event, selectedEntryHours);
                  const active = event.eventSlug === selectedEvent?.eventSlug;
                  return (
                    <li key={event.eventSlug}>
                      <button
                        type="button"
                        className={`weather-event-item ${active ? 'active' : ''}`}
                        onClick={() => setSelectedEventSlug(event.eventSlug)}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                          <strong>{fmtDateShort(event.date)}</strong>
                          {run ? <span className={`mono ${run.pnl >= 0 ? 'pos' : 'neg'}`}>{run.pnl.toFixed(3)}</span> : null}
                        </div>
                        <div className="muted" style={{ fontSize: 12 }}>
                          winner: {event.winnerLabel ?? 'n/a'}
                        </div>
                        {run ? (
                          <div className="weather-chip-row">
                            <span className="weather-chip">{run.entryHours}h</span>
                            <span className="weather-chip">{run.selectionMode.replaceAll('_', ' ')}</span>
                          </div>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          ) : null}
        </section>

        <section className="col-config weather-panel">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="card" style={{ padding: 16 }}>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Research Controls
              </div>
              <div className="weather-form-grid">
                <label>
                  <span className="field-label">City</span>
                  <select className="input" value={cityPresetValue} onChange={(e) => handleCityPresetChange(e.target.value)}>
                    {CITY_PRESETS.map((city) => (
                      <option key={city.slug} value={city.slug}>
                        {city.label}
                      </option>
                    ))}
                    <option value={CUSTOM_CITY_VALUE}>Custom slug…</option>
                  </select>
                </label>
                <label>
                  <span className="field-label">City slug</span>
                  <input className="input mono" value={citySlugInput} onChange={(e) => handleCitySlugChange(e.target.value)} readOnly={!isCustomCity} />
                </label>
                <label>
                  <span className="field-label">City label</span>
                  <input className="input" value={cityLabelInput} onChange={(e) => setCityLabelInput(e.target.value)} readOnly={!isCustomCity} />
                </label>
                <label>
                  <span className="field-label">Anchor date</span>
                  <input className="input mono" type="date" value={anchorDateInput} onChange={(e) => setAnchorDateInput(e.target.value)} />
                </label>
                <label>
                  <span className="field-label">Days</span>
                  <input className="input mono" type="number" min={1} value={daysInput} onChange={(e) => setDaysInput(e.target.value)} />
                </label>
                <label>
                  <span className="field-label">Entry hours</span>
                  <input className="input mono" value={entryHoursInput} onChange={(e) => setEntryHoursInput(e.target.value)} />
                </label>
                <label>
                  <span className="field-label">Threshold</span>
                  <input className="input mono" type="number" min={0.01} max={0.99} step={0.01} value={thresholdInput} onChange={(e) => setThresholdInput(e.target.value)} />
                </label>
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <button className="btn btn-primary" type="button" onClick={submitGenerator} disabled={status === 'loading'}>
                  {status === 'loading' ? 'Refreshing…' : 'Refresh From APIs'}
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={!selectedPresetHasArchive}
                  onClick={() => {
                    void loadBundledDataset(citySlugInput.trim().toLowerCase()).catch((err: unknown) => {
                      setError(err instanceof Error ? err.message : String(err));
                      setStatus('error');
                    });
                  }}
                >
                  Load Local Archive
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => {
                    setCityPresetValue('chengdu');
                    setCitySlugInput('chengdu');
                    setCityLabelInput('Chengdu');
                    setAnchorDateInput('2026-06-19');
                    setDaysInput('17');
                    setEntryHoursInput('6,12,18,24,36');
                    setThresholdInput('0.5');
                    void loadBundledDataset('chengdu').catch(() => undefined);
                  }}
                >
                  Reset Defaults
                </button>
              </div>
              <p className="muted" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
                City dropdown now loads the local archive directly, so dates and entry-hour summaries switch with the city instead of staying on the last dataset.
              </p>
              {progress ? (
                <p className="mono" style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--ink-soft)' }}>
                  {progress}
                </p>
              ) : null}
            </div>

            {cityBoard.length > 0 ? (
              <div className="card" style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Local City Library
                </div>
                <div className="weather-city-board">
                  {cityBoard.map((entry) => {
                    const active = dataset?.citySlug === entry.citySlug;
                    return (
                      <button
                        key={entry.citySlug}
                        type="button"
                        className={`weather-city-card ${active ? 'active' : ''}`}
                        onClick={() => {
                          setCityPresetValue(entry.citySlug);
                          setCitySlugInput(entry.citySlug);
                          setCityLabelInput(entry.cityLabel);
                          void loadBundledDataset(entry.citySlug, entry.path).catch((err: unknown) => {
                            setError(err instanceof Error ? err.message : String(err));
                            setStatus('error');
                          });
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                          <strong>{entry.cityLabel}</strong>
                          <span className={`mono ${entry.bestTotalPnl >= 0 ? 'pos' : 'neg'}`}>{entry.bestTotalPnl.toFixed(2)}</span>
                        </div>
                        <div className="muted" style={{ fontSize: 12 }}>
                          best {entry.bestEntryHour ?? '-'}h · {entry.eventCount} days
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}

            {dataset ? (
              <>
                <div className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Entry Hour Grid
                  </div>
                  <div className="weather-hour-grid">
                    {dataset.summaryByEntryHour.map((item) => {
                      const active = item.entryHours === selectedEntryHours;
                      return (
                        <button
                          key={item.entryHours}
                          type="button"
                          className={`weather-hour-card ${active ? 'active' : ''}`}
                          onClick={() => setSelectedEntryHours(item.entryHours)}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                            <strong>{item.entryHours}h</strong>
                            {dataset.bestEntryHour === item.entryHours ? <span className="weather-pill">best</span> : null}
                          </div>
                          <div className="mono" style={{ fontSize: 20, color: item.totalPnl >= 0 ? 'var(--pos)' : 'var(--neg)' }}>
                            {item.totalPnl.toFixed(3)}
                          </div>
                          <div className="muted" style={{ fontSize: 12 }}>
                            hit {fmtPct(item.hitRate, 1)} · avg {item.avgPnl.toFixed(3)}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Date × Entry Hour
                  </div>
                  <div className="weather-matrix-wrap">
                    <table className="weather-matrix">
                      <thead>
                        <tr>
                          <th>Date</th>
                          {dataset.entryHours.map((hours) => (
                            <th key={hours}>{hours}h</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[...dataset.events].reverse().map((event) => (
                          <tr key={event.eventSlug}>
                            <th>{fmtDateShort(event.date)}</th>
                            {dataset.entryHours.map((hours) => {
                              const run = findRun(event, hours);
                              const active = event.eventSlug === selectedEvent?.eventSlug && hours === selectedEntryHours;
                              return (
                                <td key={`${event.eventSlug}-${hours}`}>
                                  <button
                                    type="button"
                                    className={`weather-matrix-cell ${active ? 'active' : ''}`}
                                    style={{ background: run ? toneForPnl(run.pnl) : 'rgba(122, 105, 81, 0.08)' }}
                                    onClick={() => {
                                      setSelectedEventSlug(event.eventSlug);
                                      setSelectedEntryHours(hours);
                                    }}
                                    title={run ? `${event.date} · ${hours}h · ${run.reason}` : `${event.date} · ${hours}h`}
                                  >
                                    {run ? run.pnl.toFixed(2) : '-'}
                                  </button>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            ) : null}
          </div>
        </section>

        <section className="col-results">
          {dataset && selectedEvent && selectedRun && entrySummary ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="weather-hero card rise">
                <div>
                  <div className="eyebrow">Selected Run</div>
                  <h2 style={{ marginTop: 4 }}>
                    {dataset.cityLabel} · {selectedEvent.date} · {selectedRun.entryHours}h before close
                  </h2>
                  <p className="muted" style={{ margin: '8px 0 0' }}>
                    {selectedEvent.eventTitle} resolved to <strong>{selectedEvent.winnerLabel}</strong>. Entry on{' '}
                    <span className="mono">{fmtDateTime(selectedRun.entryTimeUtc)}</span> UTC.
                  </p>
                </div>
                <div className="weather-hero-metrics">
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Run PnL</span>
                    <strong className={`mono ${selectedRun.pnl >= 0 ? 'pos' : 'neg'}`}>{selectedRun.pnl.toFixed(3)}</strong>
                  </div>
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Selection</span>
                    <strong>{selectedRun.selectedLabels.length || 0} bucket</strong>
                  </div>
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Hit</span>
                    <strong>{selectedRun.didHit ? 'Yes' : 'No'}</strong>
                  </div>
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Hour PnL</span>
                    <strong className={`mono ${entrySummary.totalPnl >= 0 ? 'pos' : 'neg'}`}>{entrySummary.totalPnl.toFixed(3)}</strong>
                  </div>
                </div>
              </div>

              <div className="weather-research-grid">
                <section className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Alpha Notes
                  </div>
                  <div className="weather-note-list">
                    {alphaNotes.map((note) => (
                      <p key={note} className="weather-note">
                        {note}
                      </p>
                    ))}
                  </div>
                </section>

                <section className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Capacity & Friction
                  </div>
                  <div className="weather-capacity-grid">
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Selected Vol</span>
                      <strong>{fmtCompact(capacitySummary.selectedVolume)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">24h Vol</span>
                      <strong>{fmtCompact(capacitySummary.selectedVolume24hr)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Liquidity</span>
                      <strong>{fmtCompact(capacitySummary.selectedLiquidity)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Median Spread</span>
                      <strong>{capacitySummary.medianSpread == null ? '-' : fmtPct(capacitySummary.medianSpread / 100, 2)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Avg Stale Min</span>
                      <strong>{fmtMaybe(capacitySummary.avgStaleMinutes, 1)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">1h Move</span>
                      <strong>{capacitySummary.avgMove1h == null ? '-' : fmtPct(capacitySummary.avgMove1h, 1)}</strong>
                    </div>
                  </div>
                  <p className="muted weather-footnote">
                    Volume, liquidity, min size, and spread are rough market-capacity proxies from Polymarket market payloads. Staleness, updates, and 1h move are reconstructed from price history at the entry timestamp and are the better slippage warning signals here.
                  </p>
                </section>
              </div>

              <section className="card" style={{ padding: 16 }}>
                <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, marginBottom: 8 }}>
                  <div>
                    <div className="eyebrow">Price History</div>
                    <h3 style={{ fontSize: 16 }}>Outcome probabilities with marked buy points</h3>
                  </div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Vertical line marks the entry timestamp. Colored circles mark bought buckets.
                  </div>
                </header>
                <LineChart
                  series={chartSeries}
                  markers={chartMarkers}
                  rules={chartRules}
                  height={340}
                  xFormat={fmtDateTime}
                  yFormat={(value) => fmtPct(value, 0)}
                />
              </section>

              <div className="weather-detail-grid">
                <section className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Why It Bought
                  </div>
                  <p style={{ margin: 0, fontSize: 14 }}>{selectedRun.reason}</p>
                  <div className="weather-chip-row" style={{ marginTop: 12 }}>
                    {selectedRun.selectedLabels.map((label, index) => (
                      <span key={label} className="weather-chip strong">
                        {label} @ {(selectedRun.selectedPrices[index] ?? 0).toFixed(3)}
                      </span>
                    ))}
                    {selectedRun.selectedLabels.length === 0 ? <span className="weather-chip">No trade</span> : null}
                  </div>
                </section>

                <section className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Same Day, Other Entry Hours
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    {selectedEvent.runs.map((run) => {
                      const active = run.entryHours === selectedRun.entryHours;
                      return (
                        <button
                          key={run.entryHours}
                          type="button"
                          className={`weather-run-row ${active ? 'active' : ''}`}
                          onClick={() => setSelectedEntryHours(run.entryHours)}
                        >
                          <span className="mono">{run.entryHours}h</span>
                          <span>{run.selectedLabels.join(' + ') || 'skip'}</span>
                          <span className={`mono ${run.pnl >= 0 ? 'pos' : 'neg'}`}>{run.pnl.toFixed(3)}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              </div>

              <section className="card" style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Entry Snapshot & Liquidity Proxies
                </div>
                <table className="weather-outcome-table">
                  <thead>
                    <tr>
                      <th>Outcome</th>
                      <th>Entry Prob</th>
                      <th>Stale Min</th>
                      <th>Updates 6h</th>
                      <th>1h Move</th>
                      <th>Vol</th>
                      <th>Spread</th>
                      <th>Min Size</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {researchRows.map((row) => {
                      const { outcome } = row;
                      return (
                        <tr key={outcome.label}>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span
                                style={{
                                  width: 10,
                                  height: 10,
                                  borderRadius: 999,
                                  background: row.selected
                                    ? COMPARE_COLORS[selectedRun.selectedLabels.indexOf(outcome.label) % COMPARE_COLORS.length]
                                    : outcome.isWinner
                                      ? CHART.position
                                      : CHART.price,
                                }}
                              />
                              {outcome.label}
                            </div>
                          </td>
                          <td className="mono">{row.entryProb == null ? '-' : fmtPct(row.entryProb, 1)}</td>
                          <td className="mono">{fmtMaybe(row.staleMinutes, 1)}</td>
                          <td className="mono">{row.updates6h}</td>
                          <td className="mono">{row.move1hAfterEntry == null ? '-' : fmtPct(row.move1hAfterEntry, 1)}</td>
                          <td className="mono">{fmtCompact(outcome.marketStats.volume)}</td>
                          <td className="mono">
                            {outcome.marketStats.spread == null ? '-' : fmtPct(outcome.marketStats.spread / 100, 2)}
                          </td>
                          <td className="mono">{fmtMaybe(outcome.marketStats.orderMinSize, 0)}</td>
                          <td>
                            <div className="weather-chip-row">
                              {row.selected ? <span className="weather-chip strong">bought</span> : null}
                              {outcome.isWinner ? <span className="weather-chip">winner</span> : null}
                              {outcome.marketStats.rewardsMinSize != null ? (
                                <span className="weather-chip">reward min {fmtMaybe(outcome.marketStats.rewardsMinSize, 0)}</span>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="muted weather-footnote">
                  `Vol`, `Spread`, and `Min Size` are not true historical order-book snapshots. Use them as market-cap proxies, then lean more heavily on `Stale Min`, `Updates 6h`, and `1h Move` when deciding whether the backtest is realistically tradable.
                </p>
              </section>

              <section className="card" style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Execution Notes
                </div>
                <div className="weather-exec-grid">
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Next Print Delay</span>
                    <strong>{fmtMaybe(capacitySummary.nextPrintDelayMinutes, 1)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Reward Min Size</span>
                    <strong>{fmtMaybe(capacitySummary.minRewardSize, 0)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Order Min Size</span>
                    <strong>{fmtMaybe(capacitySummary.minOrderSize, 0)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Prob Sum</span>
                    <strong>{fmtPct(selectedRun.selectedProbabilitySum, 1)}</strong>
                  </div>
                </div>
              </section>
            </div>
          ) : status === 'loading' ? (
            <div className="card" style={{ padding: 24 }}>
              <div className="eyebrow">Loading</div>
              <h2 style={{ marginTop: 6 }}>Preparing weather research workspace</h2>
            </div>
          ) : (
            <div className="card" style={{ padding: 24 }}>
              <div className="eyebrow" style={{ color: 'var(--neg)' }}>
                Failed to load
              </div>
              <p className="mono neg" style={{ marginBottom: 0 }}>
                {error}
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
