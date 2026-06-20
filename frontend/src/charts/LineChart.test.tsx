import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { LineChart } from './LineChart';

describe('LineChart', () => {
  it('renders one path per non-empty series', () => {
    const { container } = render(
      <LineChart
        series={[
          { label: 'A', color: '#000', points: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
          { label: 'B', color: '#111', points: [{ x: 0, y: 1 }, { x: 1, y: 0 }] },
        ]}
      />,
    );
    expect(container.querySelectorAll('path.series-line').length).toBe(2);
  });

  it('renders nothing breaking for empty series', () => {
    const { container } = render(<LineChart series={[]} />);
    expect(container.querySelector('svg')).toBeTruthy();
  });
});
