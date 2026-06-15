// Chart color constants, kept in sync with the CSS tokens in theme.css.
// SVG charts need literal colors, so they live here (single source of truth).
export const CHART = {
  equity: '#bc4a1c', // --accent
  equityWoFee: '#a8957b', // --ink-faint
  price: '#cabb9c', // --border-strong (muted reference line)
  position: '#4f7a2e', // --pos
  grid: '#e4d8c2',
  axis: '#a8957b', // --ink-faint
  text: '#7a6951', // --ink-soft
} as const;

// Distinct warm-leaning palette for comparing multiple runs.
export const COMPARE_COLORS = ['#bc4a1c', '#3d6b86', '#4f7a2e', '#9a6b1f'] as const;
