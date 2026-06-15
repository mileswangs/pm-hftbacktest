import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CompareView } from './CompareView';
import type { BacktestResult } from '../services/types';

const mk = (id: string, slug: string, earn: number): BacktestResult => ({
  id, createdAt: 0, config: { slug, strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [
    { timestamp: 0, price: 0.5, position: 0, equityWoFee: 0, fee: 0, equity: 0 },
    { timestamp: 1000, price: 0.6, position: 5, equityWoFee: earn, fee: 0, equity: earn },
  ],
  trades: [],
  metrics: { earn, sr: 0, sortino: 0, ret: earn / 100, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 0 },
});

describe('CompareView', () => {
  it('overlays both equity curves and lists both slugs', () => {
    const { container } = render(<CompareView runs={[mk('a', 's1', 9), mk('b', 's2', 12)]} onClose={vi.fn()} />);
    expect(container.querySelectorAll('path.series-line').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('s1')).toBeTruthy();
    expect(screen.getByText('s2')).toBeTruthy();
  });
});
