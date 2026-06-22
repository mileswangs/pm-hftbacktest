import { useEffect, useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import type { AppMode } from '../components/TopBar';
import { fmtDateShort, fmtNum, fmtPct } from '../lib/format';
import { STATION_PRESETS, findStationPreset } from '../metar/stationCatalog';
import type { MetarStrategyDataset, MetarTrade } from '../metar/types';
import './MetarStudyPage.css';

type LoadState = 'loading' | 'ready' | 'error';

function formatLocalHour(hourFraction: number): string {
  const hour = Math.floor(hourFraction);
  const minute = Math.round((hourFraction - hour) * 60);
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

function buildHourHistogram(trades: MetarTrade[]): { hour: number; count: number }[] {
  const counts = new Array(24).fill(0);
  for (const trade of trades) {
    counts[Math.floor(trade.deathLocalHour)] += 1;
  }
  return counts.map((count, hour) => ({ hour, count }));
}

export function MetarStudyPage({ mode, onModeChange }: { mode: AppMode; onModeChange: (mode: AppMode) => void }) {
  const [stationSlug, setStationSlug] = useState(STATION_PRESETS[0]?.slug ?? 'lemd');
  const [status, setStatus] = useState<LoadState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [dataset, setDataset] = useState<MetarStrategyDataset | null>(null);
  const [selectedThreshold, setSelectedThreshold] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setStatus('loading');
      setError(null);
      const res = await fetch(`/data/metar/${stationSlug}.json`);
      if (!res.ok) throw new Error(`Failed to load METAR dataset (${res.status})`);
      const data = (await res.json()) as MetarStrategyDataset;
      if (cancelled) return;
      setDataset(data);
      setSelectedThreshold(data.thresholds[Math.floor(data.thresholds.length / 2)] ?? data.thresholds[0] ?? null);
      setStatus('ready');
    }

    load().catch((err: unknown) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
    return () => {
      cancelled = true;
    };
  }, [stationSlug]);

  const stationPreset = findStationPreset(stationSlug);

  const filteredTrades = useMemo(() => {
    if (!dataset || selectedThreshold === null) return [];
    return dataset.trades
      .filter((trade) => trade.noEntryPrice < selectedThreshold)
      .slice()
      .sort((a, b) => (a.targetDate < b.targetDate ? 1 : -1));
  }, [dataset, selectedThreshold]);

  const histogram = useMemo(() => buildHourHistogram(filteredTrades), [filteredTrades]);
  const maxHistogramCount = Math.max(1, ...histogram.map((h) => h.count));

  const activeSummary = dataset?.summaryByThreshold.find((row) => row.threshold === selectedThreshold) ?? null;

  return (
    <div className="shell">
      <TopBar mode={mode} onModeChange={onModeChange} adapter="mock" onAdapterChange={() => undefined} />
      <div className="metar-page">
        <div className="card metar-header">
          <div className="eyebrow">METAR Study · read-only research export</div>
          <div className="metar-header-row">
            <h2>{stationPreset?.label ?? stationSlug.toUpperCase()}</h2>
            <label className="metar-station-picker">
              <span className="field-label">Station</span>
              <select className="select" value={stationSlug} onChange={(e) => setStationSlug(e.target.value)}>
                {STATION_PRESETS.map((station) => (
                  <option key={station.slug} value={station.slug}>
                    {station.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {dataset && (
            <div className="metar-header-stats">
              <div>
                <span className="eyebrow">City</span>
                <div>{dataset.cityLabel}</div>
              </div>
              <div>
                <span className="eyebrow">Settled days</span>
                <div className="mono">{dataset.eventsTotal}</div>
              </div>
              <div>
                <span className="eyebrow">Date range</span>
                <div className="mono">
                  {dataset.dateRange ? `${fmtDateShort(dataset.dateRange.start)} – ${fmtDateShort(dataset.dateRange.end)}` : '—'}
                </div>
              </div>
              <div>
                <span className="eyebrow">Resolution source</span>
                <div>
                  {dataset.resolutionSource ? (
                    <a href={dataset.resolutionSource} target="_blank" rel="noreferrer">
                      Wunderground
                    </a>
                  ) : (
                    '—'
                  )}
                </div>
              </div>
            </div>
          )}
          <p className="muted metar-strategy-note">
            Hard-elimination NO-convergence: the moment a bucket's upper bound is exceeded by the day's running METAR
            max (Madrid-local civil day), it's mathematically dead. Simulated trade = buy NO at the first recorded
            price at-or-after that moment, held to settlement. See{' '}
            <code>research/METAR_MADRID_STRATEGY_2026-06-22.md</code> for full methodology and caveats.
          </p>
        </div>

        {status === 'loading' && <div className="card metar-status">Loading…</div>}
        {status === 'error' && <div className="card metar-status metar-status-error">{error}</div>}

        {status === 'ready' && dataset && (
          <>
            <div className="card metar-summary">
              <div className="eyebrow">Summary by NO-price threshold</div>
              <table className="metar-table">
                <thead>
                  <tr>
                    <th>Threshold</th>
                    <th>Trades</th>
                    <th>Unique days</th>
                    <th>Hit rate</th>
                    <th>Avg PnL/share</th>
                    <th>Total PnL/share</th>
                    <th>Avg entry price</th>
                  </tr>
                </thead>
                <tbody>
                  {dataset.summaryByThreshold.map((row) => (
                    <tr
                      key={row.threshold}
                      className={row.threshold === selectedThreshold ? 'active' : ''}
                      onClick={() => setSelectedThreshold(row.threshold)}
                    >
                      <td className="mono">{fmtNum(row.threshold, 2)}</td>
                      <td className="mono">{row.tradeCount}</td>
                      <td className="mono">{row.uniqueDays ?? '—'}</td>
                      <td className="mono">{row.hitRate != null ? fmtPct(row.hitRate, 0) : '—'}</td>
                      <td className={`mono ${row.avgPnlPerShare != null && row.avgPnlPerShare >= 0 ? 'pos' : 'neg'}`}>
                        {row.avgPnlPerShare != null ? fmtNum(row.avgPnlPerShare, 3) : '—'}
                      </td>
                      <td className={`mono ${row.totalPnlPerShare != null && row.totalPnlPerShare >= 0 ? 'pos' : 'neg'}`}>
                        {row.totalPnlPerShare != null ? fmtNum(row.totalPnlPerShare, 2) : '—'}
                      </td>
                      <td className="mono">{row.avgNoEntryPrice != null ? fmtNum(row.avgNoEntryPrice, 3) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted metar-summary-note">Click a row to filter the trade list and histogram below.</p>
            </div>

            <div className="metar-grid-two">
              <div className="card metar-histogram">
                <div className="eyebrow">Death-time-of-day, Madrid local ({activeSummary?.tradeCount ?? 0} trades)</div>
                <div className="metar-bars">
                  {histogram.map(({ hour, count }) => (
                    <div key={hour} className="metar-bar-col" title={`${hour}:00 — ${count} trade(s)`}>
                      <div className="metar-bar" style={{ height: `${(count / maxHistogramCount) * 100}%` }} />
                      <span className="metar-bar-label">{hour}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card metar-trades">
                <div className="eyebrow">Trades at threshold {selectedThreshold != null ? fmtNum(selectedThreshold, 2) : '—'}</div>
                <div className="metar-trades-scroll">
                  <table className="metar-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Bucket</th>
                        <th>Death (local)</th>
                        <th>Running max</th>
                        <th>NO entry</th>
                        <th>Result</th>
                        <th>PnL/share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTrades.map((trade) => (
                        <tr key={`${trade.eventSlug}:${trade.bucketLabel}`}>
                          <td className="mono">{trade.targetDate}</td>
                          <td>{trade.bucketLabel}</td>
                          <td className="mono">{formatLocalHour(trade.deathLocalHour)}</td>
                          <td className="mono">{trade.runningMaxC}°C</td>
                          <td className="mono">{fmtNum(trade.noEntryPrice, 3)}</td>
                          <td className={trade.actualIsWinner ? 'neg' : 'pos'}>{trade.actualIsWinner ? 'MISS' : 'hit'}</td>
                          <td className={`mono ${trade.pnlPerShare >= 0 ? 'pos' : 'neg'}`}>{fmtNum(trade.pnlPerShare, 3)}</td>
                        </tr>
                      ))}
                      {filteredTrades.length === 0 && (
                        <tr>
                          <td colSpan={7} className="muted">
                            No trades at this threshold.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
