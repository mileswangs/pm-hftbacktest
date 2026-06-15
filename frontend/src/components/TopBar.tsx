import type { AdapterKind } from '../services/types';

export function TopBar({
  adapter,
  onAdapterChange,
}: {
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
        <h1 style={{ fontSize: 19, letterSpacing: '-0.015em' }}>
          hftbacktest <span style={{ color: 'var(--ink-faint)', fontWeight: 400 }}>· Polymarket Backtester</span>
        </h1>
      </div>

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
    </header>
  );
}
