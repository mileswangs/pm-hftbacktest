import type { BacktestResult } from '../services/types';
import { LineChart } from '../charts/LineChart';
import type { ChartSeries } from '../charts/LineChart';
import { COMPARE_COLORS } from '../theme/colors';
import { fmtMoney, fmtNum, fmtPct, fmtTime } from '../lib/format';

const ROWS: { label: string; fmt: (r: BacktestResult) => string }[] = [
  { label: 'Earn', fmt: (r) => fmtMoney(r.metrics.earn) },
  { label: 'Return', fmt: (r) => fmtPct(r.metrics.ret) },
  { label: 'Sharpe', fmt: (r) => fmtNum(r.metrics.sr) },
  { label: 'Sortino', fmt: (r) => fmtNum(r.metrics.sortino) },
  { label: 'Max Drawdown', fmt: (r) => fmtPct(r.metrics.maxDrawdown) },
  { label: 'Return / MDD', fmt: (r) => fmtNum(r.metrics.returnOverMdd) },
  { label: 'Daily Trades', fmt: (r) => fmtNum(r.metrics.dailyNumberOfTrades, 1) },
];

export function CompareView({ runs, onClose }: { runs: BacktestResult[]; onClose: () => void }) {
  const series: ChartSeries[] = runs.map((r, i) => ({
    label: `equity · ${r.config.slug}`,
    color: COMPARE_COLORS[i % COMPARE_COLORS.length],
    axis: 'left',
    points: r.series.map((p) => ({ x: p.timestamp, y: (p.equity / (r.config.bookSize || 1)) * 100 })),
  }));

  return (
    <section className="card rise" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div className="eyebrow">Compare</div>
          <h3 style={{ fontSize: 17 }}>Two-run comparison</h3>
        </div>
        <button className="btn btn-ghost" type="button" onClick={onClose}>
          Close
        </button>
      </header>

      <LineChart series={series} height={260} xFormat={fmtTime} yFormat={(v) => `${v.toFixed(1)}%`} />

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: '8px 10px' }} />
            {runs.map((r, i) => (
              <th
                key={r.id}
                className="mono"
                style={{
                  textAlign: 'right',
                  padding: '8px 10px',
                  color: COMPARE_COLORS[i % COMPARE_COLORS.length],
                  fontWeight: 600,
                  maxWidth: 160,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {r.config.slug}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr key={row.label} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="muted" style={{ padding: '8px 10px' }}>
                {row.label}
              </td>
              {runs.map((r) => (
                <td key={r.id} className="mono" style={{ textAlign: 'right', padding: '8px 10px' }}>
                  {row.fmt(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
