import { describe, it, expect } from 'vitest';
import { hashString, mulberry32 } from './prng';

describe('prng', () => {
  it('hashString is deterministic and order-sensitive', () => {
    expect(hashString('abc')).toBe(hashString('abc'));
    expect(hashString('abc')).not.toBe(hashString('acb'));
  });

  it('mulberry32 yields deterministic sequence in [0,1)', () => {
    const a = mulberry32(123);
    const b = mulberry32(123);
    const seqA = [a(), a(), a()];
    const seqB = [b(), b(), b()];
    expect(seqA).toEqual(seqB);
    for (const v of seqA) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });

  it('different seeds differ', () => {
    expect(mulberry32(1)()).not.toBe(mulberry32(2)());
  });
});
