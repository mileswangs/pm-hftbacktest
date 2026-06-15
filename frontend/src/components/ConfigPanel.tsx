import { useState } from 'react';
import type { BacktestConfig, StrategyId } from '../services/types';
import { STRATEGIES, defaultParams, clampParams, validateParams } from '../strategies/registry';
import { ParamField } from './ParamField';

const RESAMPLE_OPTIONS = ['1s', '10s', '1m'];

export function ConfigPanel({
  running,
  onRun,
}: {
  running: boolean;
  onRun: (config: BacktestConfig) => void;
}) {
  const [slug, setSlug] = useState('btc-updown-15m-1778263200');
  const [strategy, setStrategy] = useState<StrategyId>('endline');
  const [params, setParams] = useState<Record<string, number>>(() => defaultParams('endline'));
  const [bookSize, setBookSize] = useState(100);
  const [resample, setResample] = useState('1s');
  const [errors, setErrors] = useState<string[]>([]);

  const def = STRATEGIES[strategy];

  function changeStrategy(id: StrategyId) {
    setStrategy(id);
    setParams(defaultParams(id));
    setErrors([]);
  }

  function submit() {
    const clamped = clampParams(strategy, params);
    const errs = validateParams(strategy, clamped);
    if (!slug.trim()) errs.push('Market slug is required');
    if (!(bookSize > 0)) errs.push('Book size must be greater than 0');
    if (errs.length) {
      setErrors(errs);
      return;
    }
    setErrors([]);
    setParams(clamped);
    onRun({ slug: slug.trim(), strategy, params: clamped, bookSize, resample });
  }

  return (
    <section className="card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <div className="eyebrow" style={{ marginBottom: 4 }}>
          Configuration
        </div>
        <h2 style={{ fontSize: 18 }}>Run a backtest</h2>
      </div>

      <div>
        <label className="field-label" htmlFor="slug">
          Market slug
        </label>
        <input id="slug" className="input mono" type="text" value={slug} onChange={(e) => setSlug(e.target.value)} />
      </div>

      <div>
        <label className="field-label" htmlFor="strategy">
          Strategy
        </label>
        <select
          id="strategy"
          className="select"
          value={strategy}
          onChange={(e) => changeStrategy(e.target.value as StrategyId)}
        >
          {Object.values(STRATEGIES).map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <p className="muted" style={{ fontSize: 12, margin: '7px 0 0' }}>
          {def.description}
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {def.params.map((spec) => (
          <ParamField
            key={spec.key}
            spec={spec}
            value={params[spec.key]}
            onChange={(v) => setParams((p) => ({ ...p, [spec.key]: v }))}
          />
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label className="field-label" htmlFor="bookSize">
            Book size
          </label>
          <input
            id="bookSize"
            className="input mono"
            type="number"
            min={1}
            value={bookSize}
            onChange={(e) => setBookSize(Number(e.target.value))}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="resample">
            Resample
          </label>
          <select id="resample" className="select" value={resample} onChange={(e) => setResample(e.target.value)}>
            {RESAMPLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      {errors.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--neg)', fontSize: 12.5 }}>
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}

      <button className="btn btn-primary" type="button" disabled={running} onClick={submit} style={{ width: '100%' }}>
        {running ? (
          <>
            <span className="spinner" aria-hidden /> Running…
          </>
        ) : (
          '▶  Run backtest'
        )}
      </button>
    </section>
  );
}
