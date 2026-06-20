import { useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { CHART } from '../theme/colors';

export interface ChartSeries {
  label: string;
  color: string;
  axis?: 'left' | 'right'; // default 'left'
  dashed?: boolean;
  opacity?: number;
  points: { x: number; y: number }[];
}

export interface ChartMarker {
  x: number;
  y: number;
  color: string;
  label?: string;
}

export interface ChartRule {
  x: number;
  color: string;
  label?: string;
  dashed?: boolean;
}

export interface LineChartProps {
  series: ChartSeries[];
  markers?: ChartMarker[];
  rules?: ChartRule[];
  height?: number;
  xFormat?: (x: number) => string;
  yFormat?: (y: number) => string;
  yRightFormat?: (y: number) => string;
}

const identity = (v: number) => String(v);

function extent(values: number[]): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) return [min - 1, max + 1];
  return [min, max];
}

export function LineChart({
  series,
  markers = [],
  rules = [],
  height = 280,
  xFormat = identity,
  yFormat = identity,
  yRightFormat = identity,
}: LineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      if (w > 0) setWidth(w);
    };
    measure();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
  }, []);

  const leftSeries = series.filter((s) => s.axis !== 'right');
  const rightSeries = series.filter((s) => s.axis === 'right');
  const hasRight = rightSeries.length > 0;

  const pad = { t: 14, r: hasRight ? 48 : 18, b: 26, l: 50 };
  const innerW = Math.max(0, width - pad.l - pad.r);
  const innerH = Math.max(0, height - pad.t - pad.b);

  const allX = series.flatMap((s) => s.points.map((p) => p.x));
  const [xMin, xMax] = extent(allX);
  const [lMin, lMax] = extent(leftSeries.flatMap((s) => s.points.map((p) => p.y)));
  const [rMin, rMax] = extent(rightSeries.flatMap((s) => s.points.map((p) => p.y)));

  const sx = (x: number) => pad.l + (xMax === xMin ? 0.5 : (x - xMin) / (xMax - xMin)) * innerW;
  const syL = (y: number) => pad.t + (1 - (lMax === lMin ? 0.5 : (y - lMin) / (lMax - lMin))) * innerH;
  const syR = (y: number) => pad.t + (1 - (rMax === rMin ? 0.5 : (y - rMin) / (rMax - rMin))) * innerH;

  const pathFor = (s: ChartSeries) => {
    const sy = s.axis === 'right' ? syR : syL;
    let d = '';
    let pen = false;
    for (const p of s.points) {
      if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) {
        pen = false;
        continue;
      }
      d += `${pen ? 'L' : 'M'}${sx(p.x).toFixed(2)} ${sy(p.y).toFixed(2)} `;
      pen = true;
    }
    return d.trim();
  };

  // Horizontal grid + left axis ticks
  const yTicks = 4;
  const gridLines = Array.from({ length: yTicks + 1 }, (_, i) => {
    const t = i / yTicks;
    const y = pad.t + t * innerH;
    const value = lMax - t * (lMax - lMin);
    return { y, value };
  });

  const xTicks = [0, 0.33, 0.66, 1].map((t) => {
    const x = xMin + t * (xMax - xMin);
    return { x: sx(x), value: x, anchor: t === 0 ? 'start' : t === 1 ? 'end' : 'middle' };
  });

  const baseX = leftSeries[0]?.points ?? rightSeries[0]?.points ?? [];

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    if (baseX.length === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const ratio = innerW > 0 ? (mx - pad.l) / innerW : 0;
    const idx = Math.round(ratio * (baseX.length - 1));
    setHover(Math.max(0, Math.min(baseX.length - 1, idx)));
  }

  const hoverX = hover != null && baseX[hover] ? sx(baseX[hover].x) : null;
  const tooltipStyle: CSSProperties =
    hoverX != null
      ? {
          left: Math.min(width - 150, Math.max(0, hoverX + 10)),
          top: pad.t,
        }
      : {};

  return (
    <div ref={containerRef} style={{ position: 'relative', width: '100%' }}>
      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 16px', marginBottom: 8 }}>
        {series.map((s) => (
          <span
            key={s.label}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--ink-soft)' }}
          >
            <span
              style={{
                width: 14,
                height: 0,
                borderTop: `2px ${s.dashed ? 'dashed' : 'solid'} ${s.color}`,
                display: 'inline-block',
              }}
            />
            {s.label}
          </span>
        ))}
      </div>

      <svg
        width={width}
        height={height}
        role="img"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: 'block', overflow: 'visible' }}
      >
        {/* grid */}
        {gridLines.map((g, i) => (
          <g key={i}>
            <line x1={pad.l} x2={width - pad.r} y1={g.y} y2={g.y} stroke={CHART.grid} strokeWidth={1} />
            <text x={pad.l - 8} y={g.y + 3} textAnchor="end" fontSize={10} fill={CHART.axis} fontFamily="var(--font-mono)">
              {yFormat(g.value)}
            </text>
          </g>
        ))}

        {/* right axis labels */}
        {hasRight &&
          gridLines.map((g, i) => {
            const t = i / yTicks;
            const value = rMax - t * (rMax - rMin);
            return (
              <text
                key={`r${i}`}
                x={width - pad.r + 8}
                y={g.y + 3}
                textAnchor="start"
                fontSize={10}
                fill={CHART.axis}
                fontFamily="var(--font-mono)"
              >
                {yRightFormat(value)}
              </text>
            );
          })}

        {/* x ticks */}
        {xTicks.map((tk, i) => (
          <text
            key={`x${i}`}
            x={tk.x}
            y={height - 8}
            textAnchor={tk.anchor as 'start' | 'middle' | 'end'}
            fontSize={10}
            fill={CHART.axis}
            fontFamily="var(--font-mono)"
          >
            {xFormat(tk.value)}
          </text>
        ))}

        {/* crosshair */}
        {hoverX != null && (
          <line x1={hoverX} x2={hoverX} y1={pad.t} y2={height - pad.b} stroke={CHART.axis} strokeWidth={1} strokeDasharray="3 3" opacity={0.7} />
        )}

        {/* entry rules */}
        {rules.map((rule) => (
          <g key={`rule-${rule.x}-${rule.label ?? ''}`}>
            <line
              x1={sx(rule.x)}
              x2={sx(rule.x)}
              y1={pad.t}
              y2={height - pad.b}
              stroke={rule.color}
              strokeWidth={1.25}
              strokeDasharray={rule.dashed ? '5 4' : '2 3'}
              opacity={0.85}
            />
            {rule.label ? (
              <text
                x={Math.min(width - pad.r - 2, sx(rule.x) + 4)}
                y={pad.t + 12}
                textAnchor="start"
                fontSize={10}
                fill={rule.color}
                fontFamily="var(--font-mono)"
              >
                {rule.label}
              </text>
            ) : null}
          </g>
        ))}

        {/* series */}
        {series.map((s) => (
          <path
            key={s.label}
            className="series-line"
            d={pathFor(s)}
            fill="none"
            stroke={s.color}
            strokeWidth={1.75}
            strokeLinejoin="round"
            strokeLinecap="round"
            strokeDasharray={s.dashed ? '5 4' : undefined}
            opacity={s.opacity ?? (s.dashed ? 0.7 : 1)}
          />
        ))}

        {/* explicit markers */}
        {markers.map((marker) => (
          <g key={`marker-${marker.label ?? ''}-${marker.x}-${marker.y}`}>
            <circle cx={sx(marker.x)} cy={syL(marker.y)} r={4} fill={marker.color} stroke="var(--surface)" strokeWidth={1.5} />
            {marker.label ? (
              <text
                x={Math.min(width - pad.r - 2, sx(marker.x) + 6)}
                y={Math.max(pad.t + 12, syL(marker.y) - 8)}
                textAnchor="start"
                fontSize={10}
                fill={marker.color}
                fontFamily="var(--font-mono)"
              >
                {marker.label}
              </text>
            ) : null}
          </g>
        ))}

        {/* hover dots */}
        {hover != null &&
          series.map((s) => {
            const p = s.points[hover];
            if (!p || !Number.isFinite(p.y)) return null;
            const sy = s.axis === 'right' ? syR : syL;
            return <circle key={`d${s.label}`} cx={sx(p.x)} cy={sy(p.y)} r={3} fill={s.color} stroke="var(--surface)" strokeWidth={1.5} />;
          })}
      </svg>

      {/* tooltip */}
      {hover != null && baseX[hover] && (
        <div
          className="card mono"
          style={{
            position: 'absolute',
            pointerEvents: 'none',
            padding: '6px 9px',
            fontSize: 11,
            lineHeight: 1.5,
            boxShadow: 'var(--shadow)',
            ...tooltipStyle,
          }}
        >
          <div style={{ color: 'var(--ink-faint)', marginBottom: 2 }}>{xFormat(baseX[hover].x)}</div>
          {series.map((s) => {
            const p = s.points[hover];
            if (!p || !Number.isFinite(p.y)) return null;
            const fmt = s.axis === 'right' ? yRightFormat : yFormat;
            return (
              <div key={`t${s.label}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <span style={{ color: s.color }}>{s.label}</span>
                <span>{fmt(p.y)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
