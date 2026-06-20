import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { EquityChart } from './EquityChart';
import { PositionChart } from './PositionChart';
import type { BacktestResult } from '../services/types';

const result: BacktestResult = {
  id: 'r', createdAt: 0,
  config: { slug: 's', strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [
    { timestamp: 0, price: 0.5, position: 0, equityWoFee: 0, fee: 0, equity: 0 },
    { timestamp: 1000, price: 0.6, position: 5, equityWoFee: 10, fee: 1, equity: 9 },
  ],
  trades: [],
  metrics: { earn: 9, sr: 0, sortino: 0, ret: 0.09, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 3 },
};

describe('charts', () => {
  it('EquityChart renders an svg with series lines', () => {
    const { container } = render(<EquityChart result={result} />);
    expect(container.querySelectorAll('path.series-line').length).toBeGreaterThanOrEqual(2);
  });
  it('PositionChart renders an svg with series lines', () => {
    const { container } = render(<PositionChart result={result} />);
    expect(container.querySelectorAll('path.series-line').length).toBeGreaterThanOrEqual(1);
  });
});
