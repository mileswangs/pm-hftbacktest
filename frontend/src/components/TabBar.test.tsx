import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { TabBar } from './TabBar';

const ITEMS = [
  { id: 'overview', label: 'Overview' },
  { id: 'risk', label: 'Risk' },
] as const;

function Harness() {
  const [value, setValue] = useState<(typeof ITEMS)[number]['id']>('overview');
  return <TabBar ariaLabel="Research" items={ITEMS} value={value} onChange={setValue} />;
}

describe('TabBar', () => {
  it('changes tabs by click and keyboard', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const overview = screen.getByRole('tab', { name: 'Overview' });
    const risk = screen.getByRole('tab', { name: 'Risk' });
    expect(overview).toHaveAttribute('aria-selected', 'true');

    await user.click(risk);
    expect(risk).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{ArrowLeft}');
    expect(overview).toHaveAttribute('aria-selected', 'true');
  });
});
