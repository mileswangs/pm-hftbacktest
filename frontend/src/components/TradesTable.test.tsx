import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TradesTable } from './TradesTable';

describe('TradesTable', () => {
  it('renders a row per trade', () => {
    render(
      <TradesTable
        trades={[
          { timestamp: 0, side: 'buy', price: 0.6, qty: 5 },
          { timestamp: 1000, side: 'sell', price: 1.0, qty: 5 },
        ]}
      />,
    );
    expect(screen.getAllByRole('row').length).toBe(3); // header + 2
  });

  it('shows an empty state when no trades', () => {
    render(<TradesTable trades={[]} />);
    expect(screen.getByText(/no trades/i)).toBeTruthy();
  });
});
