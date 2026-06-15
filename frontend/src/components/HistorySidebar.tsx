import type { BacktestResult } from '../services/types';
import { STRATEGIES } from '../strategies/registry';
import { fmtMoney, fmtTime } from '../lib/format';

export function HistorySidebar({
  runs,
  activeId,
  compareIds,
  onSelect,
  onToggleCompare,
  onCompare,
}: {
  runs: BacktestResult[];
  activeId: string | null;
  compareIds: string[];
  onSelect: (id: string) => void;
  onToggleCompare: (id: string) => void;
  onCompare: () => void;
}) {
  return (
    <aside
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        height: '100%',
        minHeight: 0,
      }}
    >
      <div className="eyebrow">History</div>

      {runs.length === 0 ? (
        <div className="muted" style={{ fontSize: 13, padding: '8px 2px' }}>
          No runs yet — configure and run a backtest.
        </div>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 7, overflow: 'auto', flex: 1 }}>
          {runs.map((r) => {
            const active = r.id === activeId;
            const checked = compareIds.includes(r.id);
            return (
              <li
                key={r.id}
                onClick={() => onSelect(r.id)}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 9,
                  padding: '10px 11px',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  background: active ? 'var(--accent-wash)' : 'var(--surface)',
                  border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                  transition: 'border-color 0.12s ease, background 0.12s ease',
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  aria-label={`compare ${r.config.slug}`}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onToggleCompare(r.id)}
                  style={{ marginTop: 2, accentColor: 'var(--accent)' }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.config.slug}
                  </div>
                  <div className="muted" style={{ fontSize: 11 }}>
                    {STRATEGIES[r.config.strategy].label.split(' ')[0]} · <span className="mono">{fmtTime(r.createdAt)}</span>
                  </div>
                </div>
                <div className={`mono ${r.metrics.earn >= 0 ? 'pos' : 'neg'}`} style={{ fontSize: 12.5, fontWeight: 600 }}>
                  {fmtMoney(r.metrics.earn)}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <button
        className="btn btn-ghost"
        type="button"
        disabled={compareIds.length !== 2}
        onClick={onCompare}
        style={{ width: '100%' }}
      >
        Compare {compareIds.length === 2 ? 'selected' : `(${compareIds.length}/2)`}
      </button>
    </aside>
  );
}
