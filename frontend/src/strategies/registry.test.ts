import { describe, it, expect } from 'vitest';
import { STRATEGIES, defaultParams, clampParams, validateParams } from './registry';

describe('registry', () => {
  it('exposes endline and reverse with params', () => {
    expect(STRATEGIES.endline.params.map((p) => p.key)).toEqual(['up_trigger', 'stop_long', 'order_qty']);
    expect(STRATEGIES.reverse.params.map((p) => p.key)).toEqual(['entry_price', 'stop_earn', 'cancel_after_s', 'order_qty']);
  });

  it('defaultParams returns spec defaults', () => {
    expect(defaultParams('endline')).toEqual({ up_trigger: 0.84, stop_long: 0.4, order_qty: 5 });
  });

  it('clampParams clamps out-of-range and rounds integer params', () => {
    const c = clampParams('reverse', { entry_price: 2, stop_earn: -1, cancel_after_s: 12.7, order_qty: -3 });
    expect(c.entry_price).toBe(0.99);
    expect(c.stop_earn).toBe(0.01);
    expect(c.cancel_after_s).toBe(13);
    expect(c.order_qty).toBe(0);
  });

  it('validateParams reports out-of-range keys', () => {
    expect(validateParams('endline', { up_trigger: 0.84, stop_long: 0.4, order_qty: 5 })).toEqual([]);
    const errs = validateParams('endline', { up_trigger: 5, stop_long: 0.4, order_qty: 5 });
    expect(errs.length).toBe(1);
    expect(errs[0]).toContain('up_trigger');
  });
});
