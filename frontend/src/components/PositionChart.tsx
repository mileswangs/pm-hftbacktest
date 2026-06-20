import type { BacktestResult } from '../services/types';
import { LineChart } from '../charts/LineChart';
import type { ChartSeries } from '../charts/LineChart';
import { CHART } from '../theme/colors';
import { fmtTime } from '../lib/format';

export function PositionChart({ result }: { result: BacktestResult }) {
  const { series } = result;

  const chart: ChartSeries[] = [
    { label: 'Position', color: CHART.position, axis: 'left', points: series.map((p) => ({ x: p.timestamp, y: p.position })) },
    { label: 'Price', color: CHART.price, axis: 'right', dashed: true, points: series.map((p) => ({ x: p.timestamp, y: p.price })) },
  ];

  return (
    <section className="card" style={{ padding: 16 }}>
      <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
        <h3 style={{ fontSize: 16 }}>Position</h3>
        <span className="eyebrow">qty held</span>
      </header>
      <LineChart
        series={chart}
        height={220}
        xFormat={fmtTime}
        yFormat={(v) => v.toFixed(0)}
        yRightFormat={(v) => v.toFixed(2)}
      />
    </section>
  );
}
