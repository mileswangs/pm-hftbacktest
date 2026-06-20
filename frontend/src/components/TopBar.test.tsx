import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TopBar } from './TopBar';

describe('TopBar', () => {
  it('shows the title and current adapter, fires change', () => {
    const onChange = vi.fn();
    const onModeChange = vi.fn();
    render(<TopBar mode="dashboard" onModeChange={onModeChange} adapter="mock" onAdapterChange={onChange} />);
    expect(screen.getByText(/Polymarket Backtester/i)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/adapter/i), { target: { value: 'http' } });
    expect(onChange).toHaveBeenCalledWith('http');
  });
});
