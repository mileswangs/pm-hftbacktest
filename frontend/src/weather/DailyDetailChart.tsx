import { useMemo } from 'react';
import type { ChartBand, ChartMarker, ChartRule, ChartSeries } from '../charts/LineChart';
import { LineChart } from '../charts/LineChart';
import { CHART, COMPARE_COLORS } from '../theme/colors';
import { fmtDateTime, fmtPct } from '../lib/format';
import { nearbyBucketLabels, outcomeColor } from './researchAnalytics';
import type { WeatherEvent, WeatherRun } from './types';

function splitAtEntry(points: { t: number; p: number }[], entryTs: number, endTs: number) {
  const before = points.map((pt) => ({ x: pt.t, y: pt.t <= entryTs ? pt.p : NaN }));
  const after = points.map((pt) => ({ x: pt.t, y: pt.t >= entryTs && pt.t <= endTs ? pt.p : NaN }));
  return { before, after };
}

export function DailyDetailChart({
  event,
  run,
  height = 280,
}: {
  event: WeatherEvent;
  run: WeatherRun;
  height?: number;
}) {
  const endTimestamp = useMemo(() => new Date(event.endTimeUtc).getTime(), [event.endTimeUtc]);
  const mainstream = useMemo(() => nearbyBucketLabels(event, run, 2), [event, run]);
  const visibleOutcomes = useMemo(() => {
    const filtered = event.outcomes.filter((outcome) => mainstream.has(outcome.label));
    return filtered.length > 0 ? filtered : event.outcomes;
  }, [event.outcomes, mainstream]);
  const topCandidateLabels = useMemo(() => new Set(run.topCandidates.map((c) => c.label)), [run.topCandidates]);

  const series = useMemo<ChartSeries[]>(() => {
    const out: ChartSeries[] = [];
    visibleOutcomes.forEach((outcome) => {
      const selectedIndex = run.selectedLabels.indexOf(outcome.label);
      if (selectedIndex < 0) {
        const style = outcomeColor(outcome, selectedIndex, topCandidateLabels);
        out.push({
          id: outcome.label,
          label: outcome.label,
          color: style.color,
          opacity: style.opacity,
          dashed: style.dashed,
          points: outcome.points.map((p) => ({ x: p.t, y: p.p })),
        });
        return;
      }

      const color = COMPARE_COLORS[selectedIndex % COMPARE_COLORS.length];
      const { before, after } = splitAtEntry(outcome.points, run.entryTimestamp, endTimestamp);
      out.push({
        id: `${outcome.label}__pre`,
        label: outcome.label,
        color,
        opacity: 0.32,
        dashed: true,
        points: before,
      });
      out.push({
        id: `${outcome.label}__held`,
        label: outcome.label,
        color,
        opacity: 1,
        strokeWidth: 2.75,
        points: after,
      });
    });
    return out;
  }, [visibleOutcomes, run, topCandidateLabels, endTimestamp]);

  const markers = useMemo<ChartMarker[]>(
    () =>
      run.selectedLabels.map((label, index) => ({
        x: run.entryTimestamp,
        y: run.selectedPrices[index] ?? 0,
        color: COMPARE_COLORS[index % COMPARE_COLORS.length],
        label: `buy ${label}`,
      })),
    [run],
  );

  const rules = useMemo<ChartRule[]>(
    () => [{ x: run.entryTimestamp, color: CHART.text, label: `${run.entryHours}h entry`, dashed: true }],
    [run],
  );

  const bands = useMemo<ChartBand[]>(
    () => [{ x1: run.entryTimestamp, x2: endTimestamp, color: CHART.position, opacity: 0.07, label: 'held to resolution' }],
    [run.entryTimestamp, endTimestamp],
  );

  return (
    <div className="weather-detail-chart">
      <div className="weather-detail-chart-header muted">
        {event.date} · bought {run.selectedLabels.join(' + ') || 'no trade'}
        {run.selectedLabels.length > 0 ? ` at ${fmtPct(run.selectedProbabilitySum, 1)}` : ''} · entry{' '}
        {fmtDateTime(run.entryTimeUtc)} UTC · resolved {event.winnerLabel ?? 'pending'}
      </div>
      <LineChart
        series={series}
        markers={markers}
        rules={rules}
        bands={bands}
        height={height}
        xFormat={(value) => new Date(value).toISOString().slice(5, 16).replace('T', ' ')}
        yFormat={(value) => fmtPct(value, 0)}
      />
    </div>
  );
}
