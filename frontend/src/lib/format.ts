export function fmtMoney(v: number): string {
  return v.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function fmtPct(v: number, digits = 2): string {
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtNum(v: number, digits = 2): string {
  return v.toFixed(digits);
}

export function fmtTime(ms: number): string {
  return new Date(ms).toISOString().slice(11, 19);
}

export function fmtDateShort(input: number | string): string {
  const d = new Date(input);
  return d.toISOString().slice(5, 10);
}

export function fmtDateTime(input: number | string): string {
  const d = new Date(input);
  return d.toISOString().slice(5, 16).replace('T', ' ');
}
