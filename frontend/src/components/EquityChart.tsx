import type { BacktestResult } from '../services/types';
import { LineChart } from '../charts/LineChart';
import type { ChartSeries } from '../charts/LineChart';
import { CHART } from '../theme/colors';
import { fmtTime } from '../lib/format';

export function EquityChart({ result }: { result: BacktestResult }) {
  const { series, config } = result;
  const book = config.bookSize || 1;

  const chart: ChartSeries[] = [
    { label: 'Equity', color: CHART.equity, axis: 'left', points: series.map((p) => ({ x: p.timestamp, y: (p.equity / book) * 100 })) },
    { label: 'Equity w/o fee', color: CHART.equityWoFee, axis: 'left', points: series.map((p) => ({ x: p.timestamp, y: (p.equityWoFee / book) * 100 })) },
    { label: 'Price', color: CHART.price, axis: 'right', dashed: true, points: series.map((p) => ({ x: p.timestamp, y: p.price })) },
  ];

  return (
    <section className="card" style={{ padding: 16 }}>
      <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 4 }}>
        <h3 style={{ fontSize: 16 }}>Equity</h3>
        <span className="eyebrow">cumulative return %</span>
      </header>
      <LineChart
        series={chart}
        height={260}
        xFormat={fmtTime}
        yFormat={(v) => `${v.toFixed(1)}%`}
        yRightFormat={(v) => v.toFixed(2)}
      />
    </section>
  );
}
