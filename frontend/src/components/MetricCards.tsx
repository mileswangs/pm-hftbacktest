import type { MetricSet } from '../services/types';
import { fmtMoney, fmtNum, fmtPct } from '../lib/format';

const sign = (v: number) => (v > 0 ? 'var(--pos)' : v < 0 ? 'var(--neg)' : 'var(--ink)');

export function MetricCards({ metrics: m }: { metrics: MetricSet }) {
  const items: { label: string; value: string; color?: string }[] = [
    { label: 'Earn', value: fmtMoney(m.earn), color: sign(m.earn) },
    { label: 'Return', value: fmtPct(m.ret), color: sign(m.ret) },
    { label: 'Sharpe', value: fmtNum(m.sr) },
    { label: 'Sortino', value: fmtNum(m.sortino) },
    { label: 'Max Drawdown', value: fmtPct(m.maxDrawdown), color: 'var(--neg)' },
    { label: 'Return / MDD', value: fmtNum(m.returnOverMdd) },
    { label: 'Daily Trades', value: fmtNum(m.dailyNumberOfTrades, 1) },
    { label: 'Max Pos Value', value: fmtMoney(m.maxPositionValue) },
  ];

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(128px, 1fr))',
        gap: 10,
      }}
    >
      {items.map((it) => (
        <div key={it.label} className="card" style={{ padding: '11px 13px' }}>
          <div className="eyebrow" style={{ marginBottom: 7 }}>
            {it.label}
          </div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 500, color: it.color ?? 'var(--ink)', letterSpacing: '-0.01em' }}>
            {it.value}
          </div>
        </div>
      ))}
    </div>
  );
}
