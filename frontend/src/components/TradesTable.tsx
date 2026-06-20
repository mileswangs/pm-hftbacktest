import type { Trade } from '../services/types';
import { fmtNum, fmtTime } from '../lib/format';

export function TradesTable({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <div className="muted" style={{ padding: '28px 14px', textAlign: 'center', fontSize: 13 }}>
        No trades in this run.
      </div>
    );
  }

  return (
    <div style={{ maxHeight: 360, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ position: 'sticky', top: 0, background: 'var(--surface-2)' }}>
            <th style={th}>Time</th>
            <th style={th}>Side</th>
            <th style={{ ...th, textAlign: 'right' }}>Price</th>
            <th style={{ ...th, textAlign: 'right' }}>Qty</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="mono" style={td}>{fmtTime(t.timestamp)}</td>
              <td style={{ ...td, fontWeight: 600 }}>
                <span className={t.side === 'buy' ? 'pos' : 'neg'} style={{ textTransform: 'uppercase', letterSpacing: '0.04em', fontSize: 11.5 }}>
                  {t.side}
                </span>
              </td>
              <td className="mono" style={{ ...td, textAlign: 'right' }}>{fmtNum(t.price, 3)}</td>
              <td className="mono" style={{ ...td, textAlign: 'right' }}>{fmtNum(t.qty, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: 'left',
  padding: '9px 12px',
  fontSize: 10.5,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: 'var(--ink-faint)',
  fontWeight: 600,
};

const td: React.CSSProperties = { padding: '8px 12px', color: 'var(--ink)' };
