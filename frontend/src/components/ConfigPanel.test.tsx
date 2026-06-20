import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConfigPanel } from './ConfigPanel';

describe('ConfigPanel', () => {
  it('renders endline params by default and runs with a config', () => {
    const onRun = vi.fn();
    render(<ConfigPanel running={false} onRun={onRun} />);
    expect(screen.getByLabelText(/Up trigger/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /run backtest/i }));
    expect(onRun).toHaveBeenCalledTimes(1);
    const cfg = onRun.mock.calls[0][0];
    expect(cfg.strategy).toBe('endline');
    expect(cfg.params.up_trigger).toBe(0.84);
  });

  it('switching strategy swaps the param fields', () => {
    render(<ConfigPanel running={false} onRun={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/strategy/i), { target: { value: 'reverse' } });
    expect(screen.getByLabelText(/Entry price/i)).toBeTruthy();
  });

  it('disables run button while running', () => {
    render(<ConfigPanel running={true} onRun={vi.fn()} />);
    expect(screen.getByRole('button', { name: /running/i })).toBeDisabled();
  });
});
