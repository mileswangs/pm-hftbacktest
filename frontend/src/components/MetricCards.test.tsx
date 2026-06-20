import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MetricCards } from './MetricCards';

const metrics = {
  earn: 18.5, sr: 1.2, sortino: 1.5, ret: 0.18, maxDrawdown: 0.06,
  dailyNumberOfTrades: 4, returnOverMdd: 3, maxPositionValue: 30,
};

describe('MetricCards', () => {
  it('renders earn and key metric labels', () => {
    render(<MetricCards metrics={metrics} />);
    expect(screen.getByText(/earn/i)).toBeTruthy();
    expect(screen.getByText(/Sharpe/i)).toBeTruthy();
    expect(screen.getByText(/Max Drawdown/i)).toBeTruthy();
  });
});
