import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { HistorySidebar } from './HistorySidebar';
import type { BacktestResult } from '../services/types';

const mk = (id: string, slug: string): BacktestResult => ({
  id, createdAt: 0, config: { slug, strategy: 'endline', params: {}, bookSize: 100, resample: '1s' },
  series: [], trades: [],
  metrics: { earn: 1, sr: 0, sortino: 0, ret: 0.01, maxDrawdown: 0, dailyNumberOfTrades: 0, returnOverMdd: 0, maxPositionValue: 0 },
});

describe('HistorySidebar', () => {
  it('lists runs and fires onSelect', () => {
    const onSelect = vi.fn();
    render(
      <HistorySidebar runs={[mk('a', 's1'), mk('b', 's2')]} activeId="a" compareIds={[]}
        onSelect={onSelect} onToggleCompare={vi.fn()} onCompare={vi.fn()} />,
    );
    fireEvent.click(screen.getByText('s2'));
    expect(onSelect).toHaveBeenCalledWith('b');
  });

  it('enables Compare only when two are selected', () => {
    const onCompare = vi.fn();
    const { rerender } = render(
      <HistorySidebar runs={[mk('a', 's1'), mk('b', 's2')]} activeId="a" compareIds={['a']}
        onSelect={vi.fn()} onToggleCompare={vi.fn()} onCompare={onCompare} />,
    );
    expect(screen.getByRole('button', { name: /compare/i })).toBeDisabled();
    rerender(
      <HistorySidebar runs={[mk('a', 's1'), mk('b', 's2')]} activeId="a" compareIds={['a', 'b']}
        onSelect={vi.fn()} onToggleCompare={vi.fn()} onCompare={onCompare} />,
    );
    expect(screen.getByRole('button', { name: /compare/i })).not.toBeDisabled();
  });

  it('shows empty state with no runs', () => {
    render(
      <HistorySidebar runs={[]} activeId={null} compareIds={[]}
        onSelect={vi.fn()} onToggleCompare={vi.fn()} onCompare={vi.fn()} />,
    );
    expect(screen.getByText(/no runs yet/i)).toBeTruthy();
  });
});
