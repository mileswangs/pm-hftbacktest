import { useState } from 'react';
import type { BacktestResult } from '../services/types';
import { MetricCards } from './MetricCards';
import { EquityChart } from './EquityChart';
import { PositionChart } from './PositionChart';
import { TradesTable } from './TradesTable';

type Status = 'idle' | 'running' | 'error';
type Tab = 'charts' | 'trades';

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="card"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 320,
        padding: 24,
        textAlign: 'center',
      }}
    >
      <div className="muted" style={{ maxWidth: 360 }}>
        {children}
      </div>
    </div>
  );
}

export function ResultsPanel({
  status,
  error,
  result,
}: {
  status: Status;
  error: string | null;
  result: BacktestResult | null;
}) {
  const [tab, setTab] = useState<Tab>('charts');

  if (status === 'running') {
    return (
      <div className="card" style={{ minHeight: 320, padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div className="eyebrow">Running backtest…</div>
        {[60, 100, 85].map((w, i) => (
          <div
            key={i}
            className="shimmer"
            style={{ height: i === 0 ? 56 : 120, width: `${w}%`, borderRadius: 8, background: 'var(--inset)' }}
          />
        ))}
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="card" style={{ minHeight: 200, padding: 22, borderColor: 'var(--neg)' }}>
        <div className="eyebrow" style={{ color: 'var(--neg)' }}>
          Backtest failed
        </div>
        <p className="mono" style={{ color: 'var(--neg)', marginTop: 8, fontSize: 13 }}>
          {error}
        </p>
      </div>
    );
  }

  if (!result) {
    return (
      <EmptyState>
        <strong style={{ color: 'var(--ink)', display: 'block', marginBottom: 6, fontFamily: 'var(--font-display)', fontSize: 17 }}>
          No results yet
        </strong>
        Run a backtest to see metrics, equity &amp; position curves, and the trade log.
      </EmptyState>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <MetricCards metrics={result.metrics} />

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)' }}>
        {(['charts', 'trades'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            style={{
              background: 'transparent',
              border: 'none',
              borderBottom: `2px solid ${tab === t ? 'var(--accent)' : 'transparent'}`,
              color: tab === t ? 'var(--ink)' : 'var(--ink-soft)',
              padding: '8px 12px',
              fontSize: 13,
              fontWeight: 600,
              textTransform: 'capitalize',
              marginBottom: -1,
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'charts' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <EquityChart result={result} />
          <PositionChart result={result} />
        </div>
      ) : (
        <TradesTable trades={result.trades} />
      )}
    </div>
  );
}
