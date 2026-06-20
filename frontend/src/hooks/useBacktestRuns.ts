import { useCallback, useEffect, useMemo, useState } from 'react';
import type { BacktestConfig, BacktestResult } from '../services/types';
import type { BacktestService } from '../services/BacktestService';

const STORAGE_KEY = 'pm-bt-runs';
const MAX_RUNS = 20;

type Status = 'idle' | 'running' | 'error';

function loadRuns(): BacktestResult[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as BacktestResult[]) : [];
  } catch {
    return [];
  }
}

export function useBacktestRuns(service: BacktestService) {
  const [runs, setRuns] = useState<BacktestResult[]>(() => loadRuns());
  const [activeId, setActiveId] = useState<string | null>(() => loadRuns()[0]?.id ?? null);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
    } catch {
      /* ignore quota errors */
    }
  }, [runs]);

  const run = useCallback(
    async (config: BacktestConfig) => {
      setStatus('running');
      setError(null);
      try {
        const result = await service.run(config);
        setRuns((prev) => [result, ...prev].slice(0, MAX_RUNS));
        setActiveId(result.id);
        setStatus('idle');
        return result;
      } catch (e) {
        setStatus('error');
        setError(e instanceof Error ? e.message : String(e));
        throw e;
      }
    },
    [service],
  );

  const selectRun = useCallback((id: string) => setActiveId(id), []);

  const toggleCompare = useCallback((id: string) => {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 2) return [prev[1], id];
      return [...prev, id];
    });
  }, []);

  const clearCompare = useCallback(() => setCompareIds([]), []);

  const activeRun = useMemo(() => runs.find((r) => r.id === activeId) ?? null, [runs, activeId]);
  const compareRuns = useMemo(
    () => compareIds.map((id) => runs.find((r) => r.id === id)).filter(Boolean) as BacktestResult[],
    [compareIds, runs],
  );

  return {
    runs, activeRun, activeId, status, error,
    compareIds, compareRuns,
    run, selectRun, toggleCompare, clearCompare,
  };
}
