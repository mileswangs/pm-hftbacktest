import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ResultsPanel } from './ResultsPanel';
import type { BacktestResult } from '../services/types';

const result: BacktestResult = {
  id: 'r', createdAt: 0,
  config: { slug: 's', strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [
    { timestamp: 0, price: 0.5, position: 0, equityWoFee: 0, fee: 0, equity: 0 },
    { timestamp: 1000, price: 1, position: 0, equityWoFee: 9, fee: 0, equity: 9 },
  ],
  trades: [{ timestamp: 0, side: 'buy', price: 0.6, qty: 5 }],
  metrics: { earn: 9, sr: 1, sortino: 1, ret: 0.09, maxDrawdown: 0, dailyNumberOfTrades: 1, returnOverMdd: 0, maxPositionValue: 3 },
};

describe('ResultsPanel', () => {
  it('shows empty prompt when idle with no result', () => {
    render(<ResultsPanel status="idle" error={null} result={null} />);
    expect(screen.getByText(/run a backtest/i)).toBeTruthy();
  });
  it('shows error state', () => {
    render(<ResultsPanel status="error" error="boom" result={null} />);
    expect(screen.getByText(/boom/)).toBeTruthy();
  });
  it('shows metrics and can switch to trades tab', () => {
    render(<ResultsPanel status="idle" error={null} result={result} />);
    expect(screen.getByText(/Sharpe/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /trades/i }));
    expect(screen.getByRole('table')).toBeTruthy();
  });
});
