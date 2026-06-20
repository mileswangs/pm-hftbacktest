import { useEffect, useMemo, useState } from 'react';
import { LineChart } from '../charts/LineChart';
import type { ChartMarker, ChartRule, ChartSeries } from '../charts/LineChart';
import { TopBar } from '../components/TopBar';
import type { AppMode } from '../components/TopBar';
import { fmtDateShort, fmtDateTime, fmtPct } from '../lib/format';
import { CHART, COMPARE_COLORS } from '../theme/colors';
import { buildWeatherDataset, inferCityLabel, parseEntryHours } from '../weather/buildDataset';
import type { EntryHourSummary, WeatherDataset, WeatherEvent, WeatherOutcome, WeatherRun } from '../weather/types';
import './Dashboard.css';
import './WeatherResearchPage.css';

const DATA_URL = '/data/chengdu-weather-backtest.json';

type LoadState = 'loading' | 'ready' | 'error';

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
  const [progress, setProgress] = useState<string>('');
  const [selectedEntryHours, setSelectedEntryHours] = useState<number | null>(null);
  const [selectedEventSlug, setSelectedEventSlug] = useState<string | null>(null);
  const [citySlugInput, setCitySlugInput] = useState('chengdu');
  const [cityLabelInput, setCityLabelInput] = useState('Chengdu');
  const [anchorDateInput, setAnchorDateInput] = useState('2026-06-19');
  const [daysInput, setDaysInput] = useState('17');
  const [entryHoursInput, setEntryHoursInput] = useState('6,12,18,24,36');
  const [thresholdInput, setThresholdInput] = useState('0.5');

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
    setProgress('Starting scan…');
    try {
      const payload = await buildWeatherDataset({
        ...next,
        onProgress: setProgress,
      });
      setDataset(payload);
      setSelectedEntryHours(payload.bestEntryHour ?? payload.entryHours[0] ?? null);
      setSelectedEventSlug(payload.events[payload.events.length - 1]?.eventSlug ?? null);
      setStatus('ready');
      setProgress(`Loaded ${payload.events.length} resolved event(s).`);
    } catch (err: unknown) {
      setStatus('error');
      setError(err instanceof Error ? err.message : String(err));
      setProgress('');
    }
  }

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    setError(null);
    fetch(DATA_URL)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Failed to load ${DATA_URL} (${res.status})`);
        }
        return (await res.json()) as WeatherDataset;
      })
      .then((payload) => {
        if (cancelled) return;
        setDataset(payload);
        setCitySlugInput(payload.citySlug);
        setCityLabelInput(payload.cityLabel);
        setAnchorDateInput(payload.anchorDate);
        setDaysInput(String(payload.days));
        setEntryHoursInput(payload.entryHours.join(','));
        setThresholdInput(String(payload.threshold));
        setSelectedEntryHours(payload.bestEntryHour ?? payload.entryHours[0] ?? null);
        setSelectedEventSlug(payload.events[payload.events.length - 1]?.eventSlug ?? null);
        setStatus('ready');
        setProgress(`Loaded bundled sample with ${payload.events.length} resolved event(s).`);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedEvent = useMemo(
    () => dataset?.events.find((event) => event.eventSlug === selectedEventSlug) ?? dataset?.events.at(-1) ?? null,
    [dataset, selectedEventSlug],
  );
  const selectedRun = useMemo(
    () => findRun(selectedEvent, selectedEntryHours),
    [selectedEvent, selectedEntryHours],
  );
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
    runInteractiveBuild({
      citySlug,
      cityLabel,
      anchorDate: anchorDateInput,
      days,
      entryHours,
      threshold,
    }).catch(() => undefined);
  }

  return (
    <div className="shell">
      <TopBar mode={mode} onModeChange={onModeChange} adapter="mock" onAdapterChange={() => undefined} />
      <main className="grid">
        <section className="col-history weather-panel weather-list">
          <div className="eyebrow">Dates</div>
          {status === 'loading' ? <p className="muted">Loading Chengdu weather study…</p> : null}
          {status === 'error' ? <p className="neg mono">{error}</p> : null}
          {status === 'ready' && dataset ? (
            <>
              <div className="weather-overview-card card">
                <div className="eyebrow">Dataset</div>
                <h2>{dataset.cityLabel} Highest Temperature</h2>
                <p className="muted" style={{ margin: '6px 0 0' }}>
                  {dataset.events.length} resolved days, {dataset.entryHours.length} entry points, best grid result at{' '}
                  <strong>{dataset.bestEntryHour}h</strong>.
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
                Generator
              </div>
              <div className="weather-form-grid">
                <label>
                  <span className="field-label">City slug</span>
                  <input className="input mono" value={citySlugInput} onChange={(e) => setCitySlugInput(e.target.value)} />
                </label>
                <label>
                  <span className="field-label">City label</span>
                  <input className="input" value={cityLabelInput} onChange={(e) => setCityLabelInput(e.target.value)} />
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
              <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
                <button className="btn btn-primary" type="button" onClick={submitGenerator} disabled={status === 'loading'}>
                  {status === 'loading' ? 'Generating…' : 'Generate dataset'}
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={() => {
                    setCitySlugInput('chengdu');
                    setCityLabelInput('Chengdu');
                    setAnchorDateInput('2026-06-19');
                    setDaysInput('17');
                    setEntryHoursInput('6,12,18,24,36');
                    setThresholdInput('0.5');
                  }}
                >
                  Reset defaults
                </button>
              </div>
              <p className="muted" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
                Slug format follows Polymarket event URLs, for example `chengdu`, `beijing`, `tokyo`.
              </p>
              {progress ? (
                <p className="mono" style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--ink-soft)' }}>
                  {progress}
                </p>
              ) : null}
            </div>

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
                  Entry Snapshot
                </div>
                <table className="weather-outcome-table">
                  <thead>
                    <tr>
                      <th>Outcome</th>
                      <th>Entry Prob</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedEvent.outcomes
                      .map((outcome) => {
                        const idx = selectedRun.selectedLabels.indexOf(outcome.label);
                        return {
                          outcome,
                          entryProb: idx >= 0
                            ? selectedRun.selectedPrices[idx]
                            : outcome.points.filter((point) => point.t <= selectedRun.entryTimestamp).at(-1)?.p ?? null,
                        };
                      })
                      .sort((a, b) => (b.entryProb ?? -1) - (a.entryProb ?? -1))
                      .map(({ outcome, entryProb }) => {
                        const selected = selectedRun.selectedLabels.includes(outcome.label);
                        return (
                          <tr key={outcome.label}>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span
                                  style={{
                                    width: 10,
                                    height: 10,
                                    borderRadius: 999,
                                    background: selected
                                      ? COMPARE_COLORS[selectedRun.selectedLabels.indexOf(outcome.label) % COMPARE_COLORS.length]
                                      : outcome.isWinner
                                        ? CHART.position
                                        : CHART.price,
                                  }}
                                />
                                {outcome.label}
                              </div>
                            </td>
                            <td className="mono">{entryProb == null ? '-' : fmtPct(entryProb, 1)}</td>
                            <td>
                              <div className="weather-chip-row">
                                {selected ? <span className="weather-chip strong">bought</span> : null}
                                {outcome.isWinner ? <span className="weather-chip">winner</span> : null}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </section>
            </div>
          ) : status === 'loading' ? (
            <div className="card" style={{ padding: 24 }}>
              <div className="eyebrow">Loading</div>
              <h2 style={{ marginTop: 6 }}>Preparing Chengdu weather study</h2>
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
