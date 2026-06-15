import type { StrategyId } from '../services/types';

export interface ParamSpec {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
  integer?: boolean;
}

export interface StrategyDef {
  id: StrategyId;
  label: string;
  description: string;
  params: ParamSpec[];
}

export const STRATEGIES: Record<StrategyId, StrategyDef> = {
  endline: {
    id: 'endline',
    label: 'Endline (扫尾盘)',
    description: '尾盘确定性突破：向上突破买 UP，向下突破买 DOWN，触达止损线平仓。',
    params: [
      { key: 'up_trigger', label: 'Up trigger', default: 0.84, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'stop_long', label: 'Stop long', default: 0.4, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'order_qty', label: 'Order qty', default: 5, min: 0, max: 1000, step: 1 },
    ],
  },
  reverse: {
    id: 'reverse',
    label: 'Reverse (反转)',
    description: '低价挂单博弈反转，到达止盈价或超时撤单。',
    params: [
      { key: 'entry_price', label: 'Entry price', default: 0.07, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'stop_earn', label: 'Stop earn', default: 0.9, min: 0.01, max: 0.99, step: 0.01 },
      { key: 'cancel_after_s', label: 'Cancel after (s)', default: 270, min: 0, max: 3600, step: 1, integer: true },
      { key: 'order_qty', label: 'Order qty', default: 5, min: 0, max: 1000, step: 1 },
    ],
  },
};

export function defaultParams(id: StrategyId): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of STRATEGIES[id].params) out[p.key] = p.default;
  return out;
}

export function clampParams(id: StrategyId, params: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of STRATEGIES[id].params) {
    let v = params[p.key];
    if (v == null || Number.isNaN(v)) v = p.default;
    v = Math.min(p.max, Math.max(p.min, v));
    if (p.integer) v = Math.round(v);
    out[p.key] = v;
  }
  return out;
}

export function validateParams(id: StrategyId, params: Record<string, number>): string[] {
  const errs: string[] = [];
  for (const p of STRATEGIES[id].params) {
    const v = params[p.key];
    if (v == null || Number.isNaN(v)) {
      errs.push(`${p.label} (${p.key}) is required`);
    } else if (v < p.min || v > p.max) {
      errs.push(`${p.label} (${p.key}) must be between ${p.min} and ${p.max}`);
    }
  }
  return errs;
}
