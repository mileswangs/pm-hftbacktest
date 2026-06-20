import { describe, it, expect } from 'vitest';
import { getService } from './index';
import { mockAdapter } from './mockAdapter';

describe('getService', () => {
  it('defaults to mock adapter', () => {
    expect(getService()).toBe(mockAdapter);
    expect(getService('mock')).toBe(mockAdapter);
  });

  it('returns an object with run() for http', () => {
    const svc = getService('http');
    expect(typeof svc.run).toBe('function');
  });
});
