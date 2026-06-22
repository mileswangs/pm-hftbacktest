import { Fragment, useMemo, useRef, useState } from 'react';
import type { ChartMarker, ChartSeries } from '../charts/LineChart';
import { LineChart } from '../charts/LineChart';
import { CHART } from '../theme/colors';
import { fmtDateShort, fmtDateTime, fmtPct } from '../lib/format';
import { buildDailyTradeRows, findRun } from './researchAnalytics';
import type { DailyTradeRow } from './researchAnalytics';
import { DailyDetailChart } from './DailyDetailChart';
import type { WeatherDataset, WeatherOrderbookCapacityDataset } from './types';

function DailyPnlBars({
  rows,
  selectedEventSlug,
  onSelectEvent,
}: {
  rows: DailyTradeRow[];
  selectedEventSlug: string | null;
  onSelectEvent: (slug: string) => void;
}) {
  const maxAbs = Math.max(0.01, ...rows.map((row) => Math.abs(row.pnl)));
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ row: DailyTradeRow; left: number; top: number } | null>(null);

  function showTooltip(row: DailyTradeRow, target: HTMLElement) {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const wrapRect = wrap.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    setHover({
      row,
      left: targetRect.left - wrapRect.left + targetRect.width / 2,
      top: targetRect.top - wrapRect.top,
    });
  }

  return (
    <div className="daily-pnl-bars-wrap" ref={wrapRef}>
      <div className="daily-pnl-bars">
        {rows.map((row) => {
          const traded = row.selectedLabels.length > 0;
          const heightPct = traded ? Math.max(3, (Math.abs(row.pnl) / maxAbs) * 100) : 0;
          const active = row.eventSlug === selectedEventSlug;
          return (
            <button
              key={row.eventSlug}
              type="button"
              className={`daily-pnl-bar ${active ? 'active' : ''}`}
              onClick={() => onSelectEvent(row.eventSlug)}
              onMouseEnter={(e) => showTooltip(row, e.currentTarget)}
              onMouseLeave={() => setHover(null)}
              onFocus={(e) => showTooltip(row, e.currentTarget)}
              onBlur={() => setHover(null)}
            >
              <span className="daily-pnl-bar-track">
                <span className="daily-pnl-bar-zone-pos">
                  {row.pnl > 0 ? (
                    <span className={`daily-pnl-bar-fill pos ${row.didHit ? '' : 'miss'}`} style={{ height: `${heightPct}%` }} />
                  ) : null}
                </span>
                <span className="daily-pnl-bar-zone-neg">
                  {row.pnl < 0 ? (
                    <span className={`daily-pnl-bar-fill neg ${row.didHit ? '' : 'miss'}`} style={{ height: `${heightPct}%` }} />
                  ) : null}
                </span>
              </span>
              <span className="daily-pnl-bar-date mono">{fmtDateShort(row.date)}</span>
            </button>
          );
        })}
      </div>
      {hover ? (
        <div className="daily-pnl-tooltip card mono" style={{ left: hover.left, top: hover.top }}>
          <div style={{ color: 'var(--ink-faint)', marginBottom: 2 }}>{hover.row.date}</div>
          {hover.row.selectedLabels.length > 0 ? (
            <>
              <div>
                bought {hover.row.selectedLabels.join(' + ')} @ {fmtPct(hover.row.selectedProbabilitySum, 1)}
              </div>
              <div>entry {fmtDateTime(hover.row.entryTimeUtc)} UTC</div>
              <div className={hover.row.pnl >= 0 ? 'pos' : 'neg'}>pnl {hover.row.pnl.toFixed(3)}</div>
              {hover.row.depthHint ? <div>depth: {hover.row.depthHint}</div> : null}
            </>
          ) : (
            <div className="muted">no trade</div>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function DailyTradeBoard({
  dataset,
  entryHours,
  orderbookCapacity,
  selectedEventSlug,
  onSelectEvent,
}: {
  dataset: WeatherDataset;
  entryHours: number | null;
  orderbookCapacity: WeatherOrderbookCapacityDataset | null;
  selectedEventSlug: string | null;
  onSelectEvent: (slug: string) => void;
}) {
  const [expandedDate, setExpandedDate] = useState<string | null>(null);

  const rows = useMemo(
    () => buildDailyTradeRows(dataset, entryHours, orderbookCapacity),
    [dataset, entryHours, orderbookCapacity],
  );

  const cumulativeSeries = useMemo<ChartSeries[]>(
    () => [
      {
        id: 'cumulative-pnl',
        label: 'cumulative pnl',
        color: CHART.position,
        points: rows.map((row, index) => ({ x: index, y: row.cumulativePnl })),
      },
    ],
    [rows],
  );

  const cumulativeMarkers = useMemo<ChartMarker[]>(() => {
    const idx = rows.findIndex((row) => row.eventSlug === selectedEventSlug);
    if (idx < 0) return [];
    return [{ x: idx, y: rows[idx].cumulativePnl, color: CHART.equity, label: rows[idx].date }];
  }, [rows, selectedEventSlug]);

  if (rows.length === 0) {
    return <div className="card weather-panel muted">No daily trade history for this entry hour yet.</div>;
  }

  const reversedRows = [...rows].reverse();

  return (
    <div className="weather-daily-board">
      <div className="card weather-panel">
        <div className="eyebrow">Module A · Daily PnL &amp; Buys</div>
        <DailyPnlBars rows={rows} selectedEventSlug={selectedEventSlug} onSelectEvent={onSelectEvent} />
      </div>

      <div className="card weather-panel">
        <div className="eyebrow">Module B · Cumulative PnL</div>
        <LineChart
          series={cumulativeSeries}
          markers={cumulativeMarkers}
          height={200}
          xFormat={(value) => rows[Math.round(value)]?.date ?? ''}
          yFormat={(value) => value.toFixed(2)}
        />
      </div>

      <div className="card weather-panel">
        <div className="eyebrow">Module C · Daily Detail</div>
        <div className="weather-event-table-wrap">
        <table className="weather-event-table daily-trade-table">
          <thead>
            <tr>
              <th></th>
              <th>Date</th>
              <th>PnL</th>
              <th>Cum. PnL</th>
              <th>Bucket</th>
              <th>Price</th>
              <th>Hit</th>
            </tr>
          </thead>
          <tbody>
            {reversedRows.map((row) => {
              const expanded = expandedDate === row.date;
              const active = row.eventSlug === selectedEventSlug;
              const traded = row.selectedLabels.length > 0;
              return (
                <Fragment key={row.eventSlug}>
                  <tr className={active ? 'active' : undefined} onClick={() => onSelectEvent(row.eventSlug)}>
                    <td>
                      <button
                        type="button"
                        className={`daily-trade-expand-toggle ${expanded ? 'open' : ''}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setExpandedDate(expanded ? null : row.date);
                        }}
                        aria-label={expanded ? 'Collapse day detail' : 'Expand day detail'}
                      >
                        ▸
                      </button>
                    </td>
                    <td className="mono">{fmtDateShort(row.date)}</td>
                    <td className={`mono ${row.pnl >= 0 ? 'pos' : 'neg'}`}>{row.pnl.toFixed(3)}</td>
                    <td className={`mono ${row.cumulativePnl >= 0 ? 'pos' : 'neg'}`}>{row.cumulativePnl.toFixed(3)}</td>
                    <td>{traded ? row.selectedLabels.join(' + ') : '-'}</td>
                    <td className="mono">{traded ? fmtPct(row.selectedProbabilitySum, 1) : '-'}</td>
                    <td>{traded ? (row.didHit ? 'yes' : 'no') : '-'}</td>
                  </tr>
                  {expanded ? (
                    <tr className="daily-trade-expand-row">
                      <td colSpan={7}>
                        {(() => {
                          if (entryHours == null) return null;
                          const event = dataset.events.find((e) => e.eventSlug === row.eventSlug) ?? null;
                          const run = event ? findRun(event, entryHours) : null;
                          if (!event || !run) return <p className="muted">No detail available.</p>;
                          return <DailyDetailChart event={event} run={run} />;
                        })()}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  );
}
