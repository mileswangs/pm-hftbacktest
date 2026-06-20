import type { AdapterKind } from '../services/types';

export type AppMode = 'weather' | 'dashboard';

export function TopBar({
  mode,
  onModeChange,
  adapter,
  onAdapterChange,
}: {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
  adapter: AdapterKind;
  onAdapterChange: (a: AdapterKind) => void;
}) {
  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        padding: '14px 22px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--surface)',
        position: 'sticky',
        top: 0,
        zIndex: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span
          aria-hidden
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--surface)',
            background: 'var(--accent)',
            padding: '3px 7px',
            borderRadius: 5,
            fontWeight: 600,
            letterSpacing: '0.02em',
          }}
        >
          pm
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <h1 style={{ fontSize: 19, letterSpacing: '-0.015em' }}>
            hftbacktest <span style={{ color: 'var(--ink-faint)', fontWeight: 400 }}>· Polymarket Backtester</span>
          </h1>
          <div style={{ display: 'flex', gap: 8 }}>
            {[
              { id: 'weather', label: 'Weather Study' },
              { id: 'dashboard', label: 'General Backtester' },
            ].map((item) => {
              const active = mode === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`btn ${active ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => onModeChange(item.id as AppMode)}
                  style={{ padding: '5px 10px', fontSize: 12, minHeight: 0 }}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {mode === 'dashboard' ? (
        <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="eyebrow" style={{ whiteSpace: 'nowrap' }}>
            Adapter
          </span>
          <select
            aria-label="Adapter"
            className="select"
            style={{ width: 'auto', paddingRight: 28 }}
            value={adapter}
            onChange={(e) => onAdapterChange(e.target.value as AdapterKind)}
          >
            <option value="mock">Mock · offline</option>
            <option value="http">HTTP · /api/backtest</option>
          </select>
        </label>
      ) : (
        <div style={{ maxWidth: 420, textAlign: 'right' }}>
          <div className="eyebrow" style={{ marginBottom: 4 }}>
            Chengdu Weather Grid
          </div>
          <div style={{ color: 'var(--ink-soft)', fontSize: 12.5 }}>
            Multi-date scan with entry-hour comparison, buy markers, and rule explanations.
          </div>
        </div>
      )}
    </header>
  );
}
