import { describe, it, expect } from 'vitest';
import { fmtMoney, fmtPct, fmtNum, fmtTime } from './format';

describe('format', () => {
  it('fmtMoney', () => {
    expect(fmtMoney(1234.5)).toBe('$1,234.50');
  });
  it('fmtPct', () => {
    expect(fmtPct(0.1234)).toBe('12.34%');
  });
  it('fmtNum', () => {
    expect(fmtNum(3.14159, 2)).toBe('3.14');
  });
  it('fmtTime returns HH:MM:SS', () => {
    expect(fmtTime(Date.UTC(2026, 0, 1, 1, 2, 3))).toMatch(/01:02:03/);
  });
});
