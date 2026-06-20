import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { Dashboard } from './Dashboard';

beforeEach(() => localStorage.clear());

describe('Dashboard', () => {
  it('runs a backtest end-to-end with the mock adapter', async () => {
    render(<Dashboard mode="dashboard" onModeChange={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: /run backtest/i }));
    // After the mock latency resolves, metrics appear and a history item is added.
    await waitFor(() => expect(screen.getByText(/Sharpe/i)).toBeTruthy(), { timeout: 3000 });
    await waitFor(() => expect(screen.getByText(/btc-updown/i)).toBeTruthy());
  });
});
