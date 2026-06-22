import { useEffect, useMemo, useState } from 'react';
import { LineChart } from '../charts/LineChart';
import type { ChartMarker, ChartRule, ChartSeries } from '../charts/LineChart';
import { TopBar } from '../components/TopBar';
import type { AppMode } from '../components/TopBar';
import { TabBar } from '../components/TabBar';
import type { TabItem } from '../components/TabBar';
import { Drawer } from '../components/Drawer';
import { fmtDateShort, fmtDateTime, fmtPct } from '../lib/format';
import { CHART, COMPARE_COLORS } from '../theme/colors';
import { buildWeatherDataset, inferCityLabel, parseEntryHours } from '../weather/buildDataset';
import { CITY_PRESETS, CUSTOM_CITY_VALUE, findPresetCity } from '../weather/cityCatalog';
import { DailyTradeBoard } from '../weather/DailyTradeBoard';
import type {
  WeatherDataset,
  WeatherLibraryManifest,
  WeatherOrderbookCapacityDataset,
  WeatherOrderbookCapacityRow,
} from '../weather/types';
import './Dashboard.css';
import './WeatherResearchPage.css';

const LEGACY_DATA_URL = '/data/chengdu-weather-backtest.json';
const LIBRARY_MANIFEST_URL = '/data/weather/manifest.json';

type LoadState = 'loading' | 'ready' | 'error';
type WorkspaceTab = 'overview' | 'signal' | 'liquidity' | 'risk' | 'audit';

const WORKSPACE_TABS = [
  { id: 'overview', label: 'Overview', description: 'Decision and headline PnL' },
  { id: 'signal', label: 'Signal Lab', description: 'Timing and market behavior' },
  { id: 'liquidity', label: 'Liquidity', description: 'Depth, size, and friction' },
  { id: 'risk', label: 'Risk', description: 'Guardrails and drawdown' },
  { id: 'audit', label: 'Event Audit', description: 'Every historical decision' },
] as const satisfies readonly TabItem<WorkspaceTab>[];

import {
  ORDERBOOK_CAPACITY_URLS,
  average,
  buildAlphaNotes,
  buildDailyBuyPointRows,
  buildEventBacktestRows,
  buildExecutionRows,
  buildNearLockRows,
  buildResearchRowsForRun,
  buildStrategyDecision,
  buildStrategyEventRows,
  buildStrategyHourSummaries,
  clamp01,
  computeMaxConcurrentCapital,
  computeMaxDrawdown,
  findRun,
  firstPointAfter,
  fmtCompact,
  fmtMaybe,
  medianNullable,
  minNullable,
  outcomeColor,
  sumNullable,
  sumSummary,
  toneForPnl,
} from '../weather/researchAnalytics';
import type {
  ExecutionPolicy,
  OutcomeResearchRow,
  StrategyPolicy,
} from '../weather/researchAnalytics';
async function loadJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load ${url} (${res.status})`);
  }
  return (await res.json()) as T;
}

export function WeatherResearchPage({
  mode,
  onModeChange,
}: {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
}) {
  const [status, setStatus] = useState<LoadState>('loading');
  const [error, setError] = useState<string | null>(null);
  const [dataset, setDataset] = useState<WeatherDataset | null>(null);
  const [library, setLibrary] = useState<WeatherLibraryManifest | null>(null);
  const [datasetCache, setDatasetCache] = useState<Record<string, WeatherDataset>>({});
  const [progress, setProgress] = useState<string>('');
  const [dataSourceLabel, setDataSourceLabel] = useState<string>('local archive');
  const [selectedEntryHours, setSelectedEntryHours] = useState<number | null>(null);
  const [selectedEventSlug, setSelectedEventSlug] = useState<string | null>(null);
  const [citySlugInput, setCitySlugInput] = useState('chengdu');
  const [cityLabelInput, setCityLabelInput] = useState('Chengdu');
  const [cityPresetValue, setCityPresetValue] = useState('chengdu');
  const [anchorDateInput, setAnchorDateInput] = useState('2026-06-19');
  const [daysInput, setDaysInput] = useState('17');
  const [entryHoursInput, setEntryHoursInput] = useState('6,12,18,24,36');
  const [thresholdInput, setThresholdInput] = useState('0.5');
  const [slippageInput, setSlippageInput] = useState('0.015');
  const [feeInput, setFeeInput] = useState('0.005');
  const [maxStaleMinutesInput, setMaxStaleMinutesInput] = useState('90');
  const [minUpdatesInput, setMinUpdatesInput] = useState('3');
  const [maxProbabilityInput, setMaxProbabilityInput] = useState('0.82');
  const [minSignalMarginInput, setMinSignalMarginInput] = useState('0.03');
  const [maxPreEntryMoveInput, setMaxPreEntryMoveInput] = useState('0.12');
  const [orderbookCapacity, setOrderbookCapacity] = useState<WeatherOrderbookCapacityDataset | null>(null);
  const [orderbookStatus, setOrderbookStatus] = useState<LoadState>('loading');
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceTab>(() => {
    const stored = localStorage.getItem('weather-workspace-tab');
    return WORKSPACE_TABS.some((tab) => tab.id === stored) ? (stored as WorkspaceTab) : 'overview';
  });
  const [strategyPanelOpen, setStrategyPanelOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem('weather-workspace-tab', activeWorkspace);
  }, [activeWorkspace]);

  function applyDataset(payload: WeatherDataset, sourceLabel: string, progressMessage: string) {
    const preset = findPresetCity(payload.citySlug);
    setDataset(payload);
    setCitySlugInput(preset?.sourceSlug ?? payload.citySlug);
    setCityLabelInput(payload.cityLabel);
    setCityPresetValue(preset?.slug ?? CUSTOM_CITY_VALUE);
    setAnchorDateInput(payload.anchorDate);
    setDaysInput(String(payload.days));
    setEntryHoursInput(payload.entryHours.join(','));
    setThresholdInput(String(payload.threshold));
    setSelectedEntryHours(payload.bestEntryHour ?? payload.entryHours[0] ?? null);
    setSelectedEventSlug(payload.events[payload.events.length - 1]?.eventSlug ?? null);
    setDataSourceLabel(payload.dataSource ?? sourceLabel);
    setStatus('ready');
    setProgress(progressMessage);
  }

  async function loadBundledDataset(citySlug: string, explicitPath?: string) {
    if (datasetCache[citySlug]) {
      applyDataset(datasetCache[citySlug], 'local archive', `Loaded local archive for ${datasetCache[citySlug].cityLabel}.`);
      return;
    }

    const manifestEntry = library?.cities.find((entry) => entry.citySlug === citySlug) ?? null;
    const url = explicitPath ?? manifestEntry?.path ?? (citySlug === 'chengdu' ? LEGACY_DATA_URL : '');
    if (!url) {
      throw new Error(`No local dataset archive found for ${citySlug}.`);
    }

    setStatus('loading');
    setError(null);
    setProgress(`Loading local archive for ${citySlug}…`);
    const payload = await loadJson<WeatherDataset>(url);
    setDatasetCache((current) => ({ ...current, [payload.citySlug]: payload }));
    applyDataset(payload, 'local archive', `Loaded local archive for ${payload.cityLabel} (${payload.events.length} resolved event(s)).`);
  }

  async function runInteractiveBuild(next: {
    citySlug: string;
    cityLabel: string;
    anchorDate: string;
    days: number;
    entryHours: number[];
    threshold: number;
  }) {
    setStatus('loading');
    setError(null);
    setProgress('Starting live scan…');
    try {
      const payload = await buildWeatherDataset({
        ...next,
        onProgress: setProgress,
      });
      setDatasetCache((current) => ({ ...current, [payload.citySlug]: payload }));
      applyDataset(payload, 'live API scan', `Scanned ${payload.events.length} resolved event(s) from public APIs.`);
    } catch (err: unknown) {
      setStatus('error');
      setError(err instanceof Error ? err.message : String(err));
      setProgress('');
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function init() {
      setStatus('loading');
      setError(null);
      try {
        const manifest = await loadJson<WeatherLibraryManifest>(LIBRARY_MANIFEST_URL);
        if (cancelled) return;
        setLibrary(manifest);
        const defaultEntry = manifest.cities.find((entry) => entry.citySlug === 'chengdu') ?? manifest.cities[0];
        if (!defaultEntry) {
          throw new Error('Weather library manifest is empty.');
        }
        const payload = await loadJson<WeatherDataset>(defaultEntry.path);
        if (cancelled) return;
        setDatasetCache({ [payload.citySlug]: payload });
        applyDataset(payload, 'local archive', `Loaded local archive for ${payload.cityLabel} (${payload.events.length} resolved event(s)).`);
      } catch {
        if (cancelled) return;
        try {
          const payload = await loadJson<WeatherDataset>(LEGACY_DATA_URL);
          if (cancelled) return;
          setDatasetCache({ [payload.citySlug]: payload });
          applyDataset(payload, 'legacy local sample', `Loaded fallback sample for ${payload.cityLabel}.`);
        } catch (fallbackErr) {
          if (cancelled) return;
          setError(fallbackErr instanceof Error ? fallbackErr.message : String(fallbackErr));
          setStatus('error');
        }
      }
    }

    init().catch((err: unknown) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const citySlug = dataset?.citySlug ?? '';
    const entryHours = selectedEntryHours ?? -1;
    const url = ORDERBOOK_CAPACITY_URLS[citySlug]?.[entryHours];
    let cancelled = false;

    async function loadOrderbook() {
      await Promise.resolve();
      if (cancelled) return;
      if (!url) {
        setOrderbookCapacity(null);
        setOrderbookStatus('error');
        return;
      }

      setOrderbookStatus('loading');
      try {
        const payload = await loadJson<WeatherOrderbookCapacityDataset>(url);
        if (cancelled) return;
        setOrderbookCapacity(payload);
        setOrderbookStatus('ready');
      } catch {
        if (cancelled) return;
        setOrderbookCapacity(null);
        setOrderbookStatus('error');
      }
    }

    void loadOrderbook();

    return () => {
      cancelled = true;
    };
  }, [dataset?.citySlug, selectedEntryHours]);

  const selectedEvent = useMemo(
    () => dataset?.events.find((event) => event.eventSlug === selectedEventSlug) ?? dataset?.events[dataset.events.length - 1] ?? null,
    [dataset, selectedEventSlug],
  );
  const selectedRun = useMemo(() => findRun(selectedEvent, selectedEntryHours), [selectedEvent, selectedEntryHours]);
  const selectedOrderbookRows = useMemo<WeatherOrderbookCapacityRow[]>(() => {
    if (!selectedEvent || !orderbookCapacity || !selectedRun) return [];
    const labels = new Set(selectedRun.selectedLabels);
    return orderbookCapacity.rows.filter(
      (row) => row.eventSlug === selectedEvent.eventSlug && row.targetDate === selectedEvent.date && labels.has(row.bucketLabel),
    );
  }, [selectedEvent, orderbookCapacity, selectedRun]);
  const madridOrderbookByDate = useMemo(() => {
    const map = new Map<string, WeatherOrderbookCapacityRow[]>();
    if (!orderbookCapacity) return map;
    for (const row of orderbookCapacity.rows) {
      const arr = map.get(row.targetDate) ?? [];
      arr.push(row);
      map.set(row.targetDate, arr);
    }
    return map;
  }, [orderbookCapacity]);
  const totals = useMemo(() => sumSummary(dataset?.summaryByEntryHour ?? []), [dataset]);

  const chartSeries = useMemo<ChartSeries[]>(() => {
    if (!selectedEvent || !selectedRun) return [];
    const topCandidateLabels = new Set(selectedRun.topCandidates.map((item) => item.label));
    return selectedEvent.outcomes.map((outcome) => {
      const selectedIndex = selectedRun.selectedLabels.indexOf(outcome.label);
      const style = outcomeColor(outcome, selectedIndex, topCandidateLabels);
      return {
        label: outcome.label,
        color: style.color,
        opacity: style.opacity,
        dashed: style.dashed,
        points: outcome.points.map((point) => ({ x: point.t, y: point.p })),
      };
    });
  }, [selectedEvent, selectedRun]);

  const chartMarkers = useMemo<ChartMarker[]>(() => {
    if (!selectedEvent || !selectedRun) return [];
    return selectedRun.selectedLabels.map((label, index) => ({
      x: selectedRun.entryTimestamp,
      y: selectedRun.selectedPrices[index] ?? 0,
      color: COMPARE_COLORS[index % COMPARE_COLORS.length],
      label: `BUY ${label}`,
    }));
  }, [selectedEvent, selectedRun]);

  const chartRules = useMemo<ChartRule[]>(() => {
    if (!selectedRun) return [];
    return [
      {
        x: selectedRun.entryTimestamp,
        color: CHART.text,
        label: `${selectedRun.entryHours}h entry`,
        dashed: true,
      },
    ];
  }, [selectedRun]);

  const entrySummary = useMemo(
    () => dataset?.summaryByEntryHour.find((item) => item.entryHours === selectedEntryHours) ?? null,
    [dataset, selectedEntryHours],
  );

  const cityBoard = useMemo(
    () => [...(library?.cities ?? [])].sort((a, b) => b.bestTotalPnl - a.bestTotalPnl || a.cityLabel.localeCompare(b.cityLabel)),
    [library],
  );

  const alphaNotes = useMemo(() => buildAlphaNotes(dataset), [dataset]);
  const eventRows = useMemo(() => buildEventBacktestRows(dataset, selectedEntryHours), [dataset, selectedEntryHours]);
  const madridDailyBuyRows = useMemo(
    () => (dataset?.citySlug === 'madrid' ? buildDailyBuyPointRows(dataset, 36) : []),
    [dataset],
  );
  const executionPolicy = useMemo<ExecutionPolicy>(
    () => ({
      slippagePerLeg: Number.isFinite(Number(slippageInput)) ? Number(slippageInput) : 0.015,
      feePerLeg: Number.isFinite(Number(feeInput)) ? Number(feeInput) : 0.005,
      maxStaleMinutes: Number.isFinite(Number(maxStaleMinutesInput)) ? Number(maxStaleMinutesInput) : 90,
      minUpdates6h: Number.isFinite(Number(minUpdatesInput)) ? Number(minUpdatesInput) : 3,
    }),
    [slippageInput, feeInput, maxStaleMinutesInput, minUpdatesInput],
  );
  const strategyPolicy = useMemo<StrategyPolicy>(
    () => ({
      ...executionPolicy,
      maxProbabilitySum: Number.isFinite(Number(maxProbabilityInput)) ? Number(maxProbabilityInput) : 0.82,
      minSignalMargin: Number.isFinite(Number(minSignalMarginInput)) ? Number(minSignalMarginInput) : 0.03,
      maxPreEntryMove6h: Number.isFinite(Number(maxPreEntryMoveInput)) ? Number(maxPreEntryMoveInput) : 0.12,
      requireAdjacentPair: true,
    }),
    [executionPolicy, maxProbabilityInput, minSignalMarginInput, maxPreEntryMoveInput],
  );

  const executionRows = useMemo(
    () => buildExecutionRows(dataset, selectedEntryHours, executionPolicy),
    [dataset, selectedEntryHours, executionPolicy],
  );

  const executionSummary = useMemo(() => {
    const traded = executionRows.filter((row) => row.selectedLabels.length > 0);
    const passed = traded.filter((row) => !row.blockedByPolicy);
    return {
      rawTotal: executionRows.at(-1)?.cumulativeRawPnl ?? 0,
      conservativeTotal: executionRows.at(-1)?.cumulativeConservativePnl ?? 0,
      blockedTrades: traded.length - passed.length,
      passedTrades: passed.length,
      rawDrawdown: computeMaxDrawdown(executionRows, 'cumulativeRawPnl'),
      conservativeDrawdown: computeMaxDrawdown(executionRows, 'cumulativeConservativePnl'),
      maxConcurrentCapital: computeMaxConcurrentCapital(executionRows),
      avgConservativeCost: passed.length > 0 ? passed.reduce((acc, row) => acc + row.conservativeCost, 0) / passed.length : 0,
    };
  }, [executionRows]);

  const executionOverviewSeries = useMemo<ChartSeries[]>(() => {
    if (executionRows.length === 0) return [];
    return [
      {
        label: 'raw cumulative pnl',
        color: '#9a6b1f',
        dashed: true,
        opacity: 0.78,
        points: executionRows.map((row, index) => ({ x: index, y: row.cumulativeRawPnl })),
      },
      {
        label: 'conservative cumulative pnl',
        color: CHART.position,
        points: executionRows.map((row, index) => ({ x: index, y: row.cumulativeConservativePnl })),
      },
    ];
  }, [executionRows]);

  const researchRows = useMemo<OutcomeResearchRow[]>(() => buildResearchRowsForRun(selectedEvent, selectedRun), [selectedEvent, selectedRun]);
  const strategyDecision = useMemo(
    () => buildStrategyDecision(selectedEvent, selectedRun, researchRows, dataset?.threshold ?? 0.5, strategyPolicy),
    [selectedEvent, selectedRun, researchRows, dataset, strategyPolicy],
  );
  const strategyHourSummaries = useMemo(() => buildStrategyHourSummaries(dataset, strategyPolicy), [dataset, strategyPolicy]);
  const strategyHourSummaryMap = useMemo(
    () => new Map(strategyHourSummaries.map((item) => [item.entryHours, item])),
    [strategyHourSummaries],
  );
  const bestRiskAdjustedEntryHour = useMemo(() => {
    if (strategyHourSummaries.length === 0) return null;
    return [...strategyHourSummaries].sort(
      (a, b) => b.gatedTotalPnl - a.gatedTotalPnl || b.tradeCount - a.tradeCount || a.entryHours - b.entryHours,
    )[0]?.entryHours ?? null;
  }, [strategyHourSummaries]);
  const strategyEventRows = useMemo(
    () => buildStrategyEventRows(dataset, selectedEntryHours, strategyPolicy),
    [dataset, selectedEntryHours, strategyPolicy],
  );
  const strategyOverviewSeries = useMemo<ChartSeries[]>(() => {
    if (strategyEventRows.length === 0 || eventRows.length === 0) return [];
    return [
      {
        label: 'raw cumulative pnl',
        color: '#9a6b1f',
        dashed: true,
        opacity: 0.74,
        points: eventRows.map((row, index) => ({ x: index, y: row.cumulativePnl })),
      },
      {
        label: 'risk-adjusted cumulative pnl',
        color: CHART.position,
        points: strategyEventRows.map((row, index) => ({ x: index, y: row.cumulativeGatedPnl })),
      },
    ];
  }, [strategyEventRows, eventRows]);

  const selectedResearchRows = useMemo(() => researchRows.filter((row) => row.selected), [researchRows]);

  const nearLockRows = useMemo(
    () => buildNearLockRows(selectedRun, researchRows, executionPolicy),
    [selectedRun, researchRows, executionPolicy],
  );

  const capacitySummary = useMemo(() => {
    const basis = selectedResearchRows.length > 0 ? selectedResearchRows : researchRows.slice(0, 2);
    return {
      selectedVolume: sumNullable(basis.map((row) => row.outcome.marketStats.volume)),
      selectedVolume24hr: sumNullable(basis.map((row) => row.outcome.marketStats.volume24hr)),
      selectedLiquidity: sumNullable(basis.map((row) => row.outcome.marketStats.liquidity)),
      medianSpread: medianNullable(basis.map((row) => row.outcome.marketStats.spread)),
      minOrderSize: minNullable(basis.map((row) => row.outcome.marketStats.orderMinSize)),
      minRewardSize: minNullable(basis.map((row) => row.outcome.marketStats.rewardsMinSize)),
      avgStaleMinutes: average(basis.map((row) => row.staleMinutes)),
      avgUpdates6h: average(basis.map((row) => row.updates6h)),
      avgMove1h: average(basis.map((row) => row.move1hAfterEntry)),
      nextPrintDelayMinutes: average(
        basis.map((row) => {
          const next = firstPointAfter(row.outcome, selectedRun?.entryTimestamp ?? 0);
          return next && selectedRun ? (next.t - selectedRun.entryTimestamp) / 60000 : null;
        }),
      ),
    };
  }, [researchRows, selectedResearchRows, selectedRun]);

  const nearLockSummary = useMemo(() => {
    const selectedRows = nearLockRows.filter((row) => row.selected);
    const baseRows = selectedRows.length > 0 ? selectedRows : nearLockRows.slice(0, 2);
    const avgStale =
      average(baseRows.map((row) => row.staleMinutes)) ?? average(nearLockRows.map((row) => row.staleMinutes)) ?? executionPolicy.maxStaleMinutes;
    const avgUpdates =
      average(baseRows.map((row) => row.updates6h)) ?? average(nearLockRows.map((row) => row.updates6h)) ?? executionPolicy.minUpdates6h;
    const avgSpread =
      average(baseRows.map((row) => row.spread)) ?? average(nearLockRows.map((row) => row.spread)) ?? 8;
    const realizedEdge = selectedRun ? (selectedRun.didHit ? 1 : 0) - selectedRun.selectedProbabilitySum : 0;
    const marketLag = clamp01(selectedRun?.didHit ? 1 - selectedRun.selectedProbabilitySum : 0);
    const freshnessScore = clamp01(1 - avgStale / Math.max(executionPolicy.maxStaleMinutes, 1));
    const cadenceScore = clamp01(avgUpdates / Math.max(executionPolicy.minUpdates6h, 1));
    const spreadScore = clamp01(1 - avgSpread / 12);
    const lockScore = Math.round((marketLag * 0.42 + freshnessScore * 0.24 + cadenceScore * 0.2 + spreadScore * 0.14) * 100);
    const triggerCount = [
      selectedRun != null && selectedRun.entryHours >= 6 && selectedRun.entryHours <= 18,
      selectedRun != null && selectedRun.selectedProbabilitySum <= 0.82,
      avgStale <= executionPolicy.maxStaleMinutes,
      avgUpdates >= executionPolicy.minUpdates6h,
      avgSpread <= 8,
    ].filter(Boolean).length;

    return {
      lockScore,
      realizedEdge,
      avgStale,
      avgUpdates,
      avgSpread,
      triggerCount,
      windowLabel:
        selectedRun == null
          ? '-'
          : selectedRun.entryHours < 6
            ? 'sub-6h chase'
            : selectedRun.entryHours <= 18
              ? 'core 6-18h'
              : 'pre-close early',
      headline:
        selectedRun == null
          ? 'No active setup'
          : realizedEdge >= 0.12
            ? 'Captured a genuine late-day lag'
            : realizedEdge >= 0
              ? 'Edge existed, but it was already tighter'
              : 'Looked tradable, but did not lock cleanly',
      checklist: [
        {
          label: 'Settlement window',
          value: selectedRun == null ? '-' : `${selectedRun.entryHours}h to close`,
          pass: selectedRun != null && selectedRun.entryHours >= 6 && selectedRun.entryHours <= 18,
        },
        {
          label: 'Market price paid',
          value: selectedRun == null ? '-' : fmtPct(selectedRun.selectedProbabilitySum, 1),
          pass: selectedRun != null && selectedRun.selectedProbabilitySum <= 0.82,
        },
        {
          label: 'Feed freshness',
          value: `${fmtMaybe(avgStale, 1)}m`,
          pass: avgStale <= executionPolicy.maxStaleMinutes,
        },
        {
          label: 'Print cadence',
          value: `${fmtMaybe(avgUpdates, 1)} / 6h`,
          pass: avgUpdates >= executionPolicy.minUpdates6h,
        },
        {
          label: 'Spread regime',
          value: avgSpread == null ? '-' : `${avgSpread.toFixed(1)}c`,
          pass: avgSpread <= 8,
        },
      ],
    };
  }, [nearLockRows, selectedRun, executionPolicy]);

  const isCustomCity = cityPresetValue === CUSTOM_CITY_VALUE;
  const selectedArchiveSlug = cityPresetValue === CUSTOM_CITY_VALUE ? citySlugInput.trim().toLowerCase() : cityPresetValue;
  const selectedPresetHasArchive = useMemo(
    () => !!library?.cities.some((entry) => entry.citySlug === selectedArchiveSlug),
    [library, selectedArchiveSlug],
  );

  function submitGenerator() {
    const citySlug = citySlugInput.trim().toLowerCase();
    const cityLabel = cityLabelInput.trim() || inferCityLabel(citySlug);
    const days = Number(daysInput);
    const threshold = Number(thresholdInput);
    const entryHours = parseEntryHours(entryHoursInput);
    if (!citySlug) {
      setError('City slug is required.');
      setStatus('error');
      return;
    }
    if (!anchorDateInput) {
      setError('Anchor date is required.');
      setStatus('error');
      return;
    }
    if (!Number.isFinite(days) || days <= 0) {
      setError('Days must be a positive number.');
      setStatus('error');
      return;
    }
    if (!Number.isFinite(threshold) || threshold <= 0 || threshold >= 1) {
      setError('Threshold must be between 0 and 1.');
      setStatus('error');
      return;
    }
    if (entryHours.length === 0) {
      setError('Entry hours must contain at least one positive number.');
      setStatus('error');
      return;
    }
    void runInteractiveBuild({
      citySlug,
      cityLabel,
      anchorDate: anchorDateInput,
      days,
      entryHours,
      threshold,
    });
  }

  function handleCityPresetChange(value: string) {
    setCityPresetValue(value);
    if (value === CUSTOM_CITY_VALUE) {
      return;
    }
    const preset = findPresetCity(value);
    if (!preset) return;
    setCitySlugInput(preset.sourceSlug ?? preset.slug);
    setCityLabelInput(preset.label);
    void loadBundledDataset(preset.slug).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
  }

  function handleCitySlugChange(value: string) {
    const nextSlug = value.trim().toLowerCase();
    setCitySlugInput(value);
    const preset = findPresetCity(nextSlug);
    if (!preset) {
      setCityPresetValue(CUSTOM_CITY_VALUE);
      return;
    }
    setCityPresetValue(preset.slug);
    setCityLabelInput(preset.label);
    void loadBundledDataset(preset.slug).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
    });
  }

  return (
    <div className="shell">
      <TopBar
        mode={mode}
        onModeChange={onModeChange}
        adapter="mock"
        onAdapterChange={() => undefined}
        extraActions={
          mode === 'weather' ? (
            <button type="button" className="btn btn-ghost" onClick={() => setStrategyPanelOpen(true)}>
              ⚙ Strategy Params
            </button>
          ) : undefined
        }
      />

      <Drawer open={strategyPanelOpen} onClose={() => setStrategyPanelOpen(false)} title="Strategy Params">
        <div className="card weather-tab-panel" style={{ padding: 16 }}>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Research Controls
          </div>
          <div className="weather-form-grid">
            <label>
              <span className="field-label">City</span>
              <select className="input" value={cityPresetValue} onChange={(e) => handleCityPresetChange(e.target.value)}>
                {CITY_PRESETS.map((city) => (
                  <option key={city.slug} value={city.slug}>
                    {city.label}
                  </option>
                ))}
                <option value={CUSTOM_CITY_VALUE}>Custom slug…</option>
              </select>
            </label>
            <label>
              <span className="field-label">City slug</span>
              <input className="input mono" value={citySlugInput} onChange={(e) => handleCitySlugChange(e.target.value)} readOnly={!isCustomCity} />
            </label>
            <label>
              <span className="field-label">City label</span>
              <input className="input" value={cityLabelInput} onChange={(e) => setCityLabelInput(e.target.value)} readOnly={!isCustomCity} />
            </label>
            <label>
              <span className="field-label">Anchor date</span>
              <input className="input mono" type="date" value={anchorDateInput} onChange={(e) => setAnchorDateInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Days</span>
              <input className="input mono" type="number" min={1} value={daysInput} onChange={(e) => setDaysInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Entry hours</span>
              <input className="input mono" value={entryHoursInput} onChange={(e) => setEntryHoursInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Threshold</span>
              <input className="input mono" type="number" min={0.01} max={0.99} step={0.01} value={thresholdInput} onChange={(e) => setThresholdInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Slip / leg</span>
              <input className="input mono" type="number" min={0} step={0.001} value={slippageInput} onChange={(e) => setSlippageInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Fee / leg</span>
              <input className="input mono" type="number" min={0} step={0.001} value={feeInput} onChange={(e) => setFeeInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Max stale min</span>
              <input className="input mono" type="number" min={0} step={1} value={maxStaleMinutesInput} onChange={(e) => setMaxStaleMinutesInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Min updates 6h</span>
              <input className="input mono" type="number" min={0} step={1} value={minUpdatesInput} onChange={(e) => setMinUpdatesInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Max paid prob</span>
              <input className="input mono" type="number" min={0.01} max={0.99} step={0.01} value={maxProbabilityInput} onChange={(e) => setMaxProbabilityInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Min signal margin</span>
              <input className="input mono" type="number" min={0.01} max={0.5} step={0.01} value={minSignalMarginInput} onChange={(e) => setMinSignalMarginInput(e.target.value)} />
            </label>
            <label>
              <span className="field-label">Max pre-entry 6h move</span>
              <input className="input mono" type="number" min={0.01} max={0.99} step={0.01} value={maxPreEntryMoveInput} onChange={(e) => setMaxPreEntryMoveInput(e.target.value)} />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <button className="btn btn-primary" type="button" onClick={submitGenerator} disabled={status === 'loading'}>
              {status === 'loading' ? 'Refreshing…' : 'Refresh From APIs'}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={!selectedPresetHasArchive}
              onClick={() => {
                void loadBundledDataset(selectedArchiveSlug).catch((err: unknown) => {
                  setError(err instanceof Error ? err.message : String(err));
                  setStatus('error');
                });
              }}
            >
              Load Local Archive
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => {
                setCityPresetValue('chengdu');
                setCitySlugInput('chengdu');
                setCityLabelInput('Chengdu');
                setAnchorDateInput('2026-06-19');
                setDaysInput('17');
                setEntryHoursInput('6,12,18,24,36');
                setThresholdInput('0.5');
                setSlippageInput('0.015');
                setFeeInput('0.005');
                setMaxStaleMinutesInput('90');
                setMinUpdatesInput('3');
                setMaxProbabilityInput('0.82');
                setMinSignalMarginInput('0.03');
                setMaxPreEntryMoveInput('0.12');
                void loadBundledDataset('chengdu').catch(() => undefined);
              }}
            >
              Reset Defaults
            </button>
          </div>
          <p className="muted" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
            City dropdown now loads the local archive directly, so dates and entry-hour summaries switch with the city instead of staying on the last dataset.
          </p>
          {progress ? (
            <p className="mono" style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--ink-soft)' }}>
              {progress}
            </p>
          ) : null}
        </div>

        {dataset ? (
          <div className="card" style={{ padding: 16, marginTop: 14 }}>
            <div className="eyebrow" style={{ marginBottom: 8 }}>
              Entry Hour
            </div>
            <div className="weather-entry-hour-seg">
              {dataset.summaryByEntryHour.map((item) => {
                const active = item.entryHours === selectedEntryHours;
                const gated = strategyHourSummaryMap.get(item.entryHours) ?? null;
                return (
                  <button
                    key={item.entryHours}
                    type="button"
                    className={`weather-entry-hour-seg-btn ${active ? 'active' : ''}`}
                    onClick={() => setSelectedEntryHours(item.entryHours)}
                    title={`raw hit ${fmtPct(item.hitRate, 1)} · risk pnl ${gated?.gatedTotalPnl.toFixed(3) ?? '-'} · buy ${gated?.tradeCount ?? 0}/${gated?.rawTradeCount ?? item.tradedCount}`}
                  >
                    <strong>{item.entryHours}h</strong>
                    {dataset.bestEntryHour === item.entryHours ? <span className="weather-pill">best</span> : null}
                    <span className={`mono ${item.totalPnl >= 0 ? 'pos' : 'neg'}`}>{item.totalPnl.toFixed(2)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <details className="weather-advanced-details" style={{ marginTop: 14 }}>
          <summary className="eyebrow">Advanced · city library &amp; date × hour matrix</summary>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
            {cityBoard.length > 0 ? (
              <div className="card" style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Local City Library
                </div>
                <div className="weather-city-board">
                  {cityBoard.map((entry) => {
                    const active = dataset?.citySlug === entry.citySlug;
                    return (
                      <button
                        key={entry.citySlug}
                        type="button"
                        className={`weather-city-card ${active ? 'active' : ''}`}
                        onClick={() => {
                          const preset = findPresetCity(entry.citySlug);
                          setCityPresetValue(entry.citySlug);
                          setCitySlugInput(preset?.sourceSlug ?? entry.citySlug);
                          setCityLabelInput(entry.cityLabel);
                          void loadBundledDataset(entry.citySlug, entry.path).catch((err: unknown) => {
                            setError(err instanceof Error ? err.message : String(err));
                            setStatus('error');
                          });
                        }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                            <strong>{entry.cityLabel}</strong>
                            <span className={`mono ${entry.bestTotalPnl >= 0 ? 'pos' : 'neg'}`}>{entry.bestTotalPnl.toFixed(2)}</span>
                          </div>
                        <div className="muted" style={{ fontSize: 12 }}>
                          best {entry.bestEntryHour ?? '-'}h · raw cum pnl {entry.bestTotalPnl.toFixed(2)}
                        </div>
                        </button>
                      );
                  })}
                </div>
              </div>
            ) : null}

            {dataset ? (
              <div className="card" style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Date × Entry Hour
                </div>
                <div className="weather-matrix-wrap">
                  <table className="weather-matrix">
                    <thead>
                      <tr>
                        <th>Date</th>
                        {dataset.entryHours.map((hours) => (
                          <th key={hours}>{hours}h</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[...dataset.events].reverse().map((event) => (
                        <tr key={event.eventSlug}>
                          <th>{fmtDateShort(event.date)}</th>
                          {dataset.entryHours.map((hours) => {
                            const run = findRun(event, hours);
                            const active = event.eventSlug === selectedEvent?.eventSlug && hours === selectedEntryHours;
                            return (
                              <td key={`${event.eventSlug}-${hours}`}>
                                <button
                                  type="button"
                                  className={`weather-matrix-cell ${active ? 'active' : ''}`}
                                  style={{ background: run ? toneForPnl(run.pnl) : 'rgba(122, 105, 81, 0.08)' }}
                                  onClick={() => {
                                    setSelectedEventSlug(event.eventSlug);
                                    setSelectedEntryHours(hours);
                                  }}
                                  title={run ? `${event.date} · ${hours}h · ${run.reason}` : `${event.date} · ${hours}h`}
                                >
                                  {run ? run.pnl.toFixed(2) : '-'}
                                </button>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        </details>
      </Drawer>

      <main className="grid weather-grid-single">
        <section className="col-results">
          {status === 'loading' && !dataset ? <p className="muted">Loading weather research workspace…</p> : null}
          {status === 'error' && !dataset ? <p className="neg mono">{error}</p> : null}
          {dataset ? (
            <div className="weather-overview-card card">
              <div className="eyebrow">Dataset</div>
              <h2>{dataset.cityLabel} Highest Temperature</h2>
              <p className="muted" style={{ margin: '6px 0 0' }}>
                {dataset.events.length} resolved days, {dataset.entryHours.length} entry points, source: <strong>{dataSourceLabel}</strong>.
              </p>
              <div className="weather-stat-strip">
                <div>
                  <span className="eyebrow">Anchor</span>
                  <strong>{dataset.anchorDate}</strong>
                </div>
                <div>
                  <span className="eyebrow">Trades</span>
                  <strong>{totals.totalTrades}</strong>
                </div>
                <div>
                  <span className="eyebrow">Cumulative PnL</span>
                  <strong className={totals.totalPnl >= 0 ? 'pos' : 'neg'}>{totals.totalPnl.toFixed(3)}</strong>
                </div>
              </div>
              {dataset.dataSourceDetail ? (
                <p className="muted" style={{ margin: '8px 0 0', fontSize: 12.5 }}>
                  {dataset.dataSourceDetail}
                </p>
              ) : null}
            </div>
          ) : null}

          {dataset && selectedEvent && selectedRun && entrySummary ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div className="weather-hero card rise">
                <div>
                  <div className="eyebrow">Selected Run</div>
                  <h2 style={{ marginTop: 4 }}>
                    {dataset.cityLabel} · {selectedEvent.date} · {selectedRun.entryHours}h before close
                  </h2>
                  <p className="muted" style={{ margin: '8px 0 0' }}>
                    {selectedEvent.eventTitle} resolved to <strong>{selectedEvent.winnerLabel}</strong>. Entry on{' '}
                    <span className="mono">{fmtDateTime(selectedRun.entryTimeUtc)}</span> UTC.
                  </p>
                </div>
                <div className="weather-hero-metrics">
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Event PnL</span>
                    <strong className={`mono ${selectedRun.pnl >= 0 ? 'pos' : 'neg'}`}>{selectedRun.pnl.toFixed(3)}</strong>
                  </div>
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Selection</span>
                    <strong>{selectedRun.selectedLabels.length || 0} bucket</strong>
                  </div>
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Hit</span>
                    <strong>{selectedRun.didHit ? 'Yes' : 'No'}</strong>
                  </div>
                  <div className="card weather-mini-metric">
                    <span className="eyebrow">Hour Cum PnL</span>
                    <strong className={`mono ${entrySummary.totalPnl >= 0 ? 'pos' : 'neg'}`}>{entrySummary.totalPnl.toFixed(3)}</strong>
                  </div>
                </div>
              </div>

              <DailyTradeBoard
                dataset={dataset}
                entryHours={selectedEntryHours}
                orderbookCapacity={orderbookCapacity}
                selectedEventSlug={selectedEventSlug}
                onSelectEvent={setSelectedEventSlug}
              />

              <TabBar
                ariaLabel="Weather workspace"
                items={WORKSPACE_TABS.map((tab) => ({
                  ...tab,
                  badge:
                    tab.id === 'signal'
                      ? selectedRun.selectedLabels.length
                      : tab.id === 'liquidity'
                        ? selectedOrderbookRows.length
                        : tab.id === 'risk'
                          ? executionSummary.blockedTrades
                          : tab.id === 'audit'
                            ? eventRows.length
                            : undefined,
                }))}
                value={activeWorkspace}
                onChange={setActiveWorkspace}
              />

              <section
                id="weather-workspace-overview-panel"
                role="tabpanel"
                aria-labelledby="weather-workspace-overview-tab"
                hidden={activeWorkspace !== 'overview'}
                className="weather-ticket card rise weather-tab-panel"
              >
                <div className="weather-ticket-header">
                  <div>
                    <div className="eyebrow">Decision Ticket</div>
                    <h3>Can this setup actually be bought?</h3>
                    <p className="muted" style={{ margin: '8px 0 0' }}>
                      This is the strategy-side answer, not just the raw backtest answer. It applies freshness, cadence, cost, adjacency, and pre-entry volatility guardrails before allowing the trade.
                    </p>
                  </div>
                  <div className={`weather-ticket-badge ${strategyDecision.verdict}`}>
                    <span className="eyebrow">Verdict</span>
                    <strong>
                      {strategyDecision.verdict === 'trade'
                        ? 'BUY'
                        : strategyDecision.verdict === 'watch'
                          ? 'WATCH'
                          : 'SKIP'}
                    </strong>
                    <span>{strategyDecision.headline}</span>
                  </div>
                </div>

                <div className="weather-ticket-grid">
                  <div className="weather-ticket-card">
                    <span className="eyebrow">Price Paid</span>
                    <strong>{fmtPct(selectedRun.selectedProbabilitySum, 1)}</strong>
                    <span>max allowed {fmtPct(strategyPolicy.maxProbabilitySum, 0)}</span>
                  </div>
                  <div className="weather-ticket-card">
                    <span className="eyebrow">Signal Margin</span>
                    <strong>{strategyDecision.thresholdMargin == null ? '-' : fmtPct(strategyDecision.thresholdMargin, 1)}</strong>
                    <span>min required {fmtPct(strategyPolicy.minSignalMargin, 0)}</span>
                  </div>
                  <div className="weather-ticket-card">
                    <span className="eyebrow">Feed Freshness</span>
                    <strong>{fmtMaybe(strategyDecision.avgStaleMinutes, 1)}m</strong>
                    <span>cap {strategyPolicy.maxStaleMinutes}m</span>
                  </div>
                  <div className="weather-ticket-card">
                    <span className="eyebrow">Updates / 6h</span>
                    <strong>{fmtMaybe(strategyDecision.avgUpdates6h, 1)}</strong>
                    <span>floor {strategyPolicy.minUpdates6h}</span>
                  </div>
                  <div className="weather-ticket-card">
                    <span className="eyebrow">Pre-entry 6h Move</span>
                    <strong>{strategyDecision.avgMove6hBeforeEntry == null ? '-' : fmtPct(strategyDecision.avgMove6hBeforeEntry, 1)}</strong>
                    <span>cap {fmtPct(strategyPolicy.maxPreEntryMove6h, 0)}</span>
                  </div>
                  <div className="weather-ticket-card">
                    <span className="eyebrow">Pair Shape</span>
                    <strong>{strategyDecision.pairAdjacent ? 'adjacent' : 'broken'}</strong>
                    <span>{selectedRun.selectedLabels.length <= 1 ? 'single bucket' : 'pair structure check'}</span>
                  </div>
                </div>

                {strategyDecision.reasons.length > 0 ? (
                  <div className="weather-ticket-flags">
                    {strategyDecision.reasons.map((reason) => (
                      <div key={reason} className="weather-ticket-flag danger">
                        {reason}
                      </div>
                    ))}
                  </div>
                ) : null}
                {strategyDecision.warnings.length > 0 ? (
                  <div className="weather-ticket-flags">
                    {strategyDecision.warnings.map((warning) => (
                      <div key={warning} className="weather-ticket-flag watch">
                        {warning}
                      </div>
                    ))}
                  </div>
                ) : null}
              </section>

              <section
                id="weather-workspace-liquidity-panel"
                role="tabpanel"
                aria-labelledby="weather-workspace-liquidity-tab"
                hidden={activeWorkspace !== 'liquidity'}
                className="card weather-tab-panel"
                style={{ padding: 16 }}
              >
                <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, marginBottom: 8 }}>
                  <div>
                    <div className="eyebrow">Historical Entry Depth</div>
                    <h3 style={{ fontSize: 16 }}>How much size looked available near the buy point?</h3>
                  </div>
                  <div className="muted" style={{ fontSize: 12, maxWidth: 460, textAlign: 'right' }}>
                    `snapshot size` is the visible PMXT size attached to the last selected entry snapshot. Full ladder fields appear only when a nearby `book` snapshot was captured.
                  </div>
                </header>
                {orderbookStatus === 'ready' && selectedOrderbookRows.length > 0 ? (
                  <>
                    <div className="weather-capacity-grid">
                      {selectedOrderbookRows.map((row) => (
                        <div key={`${row.targetDate}-${row.bucketLabel}`} className="weather-capacity-item">
                          <span className="eyebrow">{row.bucketLabel}</span>
                          <strong>{row.snapshotSize == null ? '-' : fmtCompact(row.snapshotSize, 1)} sh</strong>
                          <span className="muted">
                            ask {row.snapshotBestAsk == null ? '-' : fmtPct(row.snapshotBestAsk, 1)}
                            {row.cumSizePlus1c != null ? ` · +1c ${fmtCompact(row.cumSizePlus1c, 1)} sh` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                    <div className="weather-event-table-wrap" style={{ marginTop: 12 }}>
                      <table className="weather-event-table">
                        <thead>
                          <tr>
                            <th>Bucket</th>
                            <th>Paid</th>
                            <th>Snapshot Ask</th>
                            <th>Snapshot Size</th>
                            <th>Top Ask</th>
                            <th>Size +1c</th>
                            <th>Size +2c</th>
                            <th>Size +5c</th>
                            <th>Book Age</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedOrderbookRows.map((row) => (
                            <tr key={`${row.targetDate}-${row.bucketLabel}`}>
                              <td>{row.bucketLabel}</td>
                              <td className="mono">{fmtPct(row.selectedProbability, 1)}</td>
                              <td className="mono">{row.snapshotBestAsk == null ? '-' : fmtPct(row.snapshotBestAsk, 1)}</td>
                              <td className="mono">{row.snapshotSize == null ? '-' : fmtCompact(row.snapshotSize, 1)}</td>
                              <td className="mono">{row.topAskPrice == null ? '-' : fmtPct(row.topAskPrice, 1)}</td>
                              <td className="mono">{row.cumSizePlus1c == null ? '-' : fmtCompact(row.cumSizePlus1c, 1)}</td>
                              <td className="mono">{row.cumSizePlus2c == null ? '-' : fmtCompact(row.cumSizePlus2c, 1)}</td>
                              <td className="mono">{row.cumSizePlus5c == null ? '-' : fmtCompact(row.cumSizePlus5c, 1)}</td>
                              <td className="mono">{fmtMaybe(row.bookAgeMinutes, 1)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p className="muted" style={{ margin: 0 }}>
                    {dataset.citySlug === 'madrid' && selectedEntryHours === 36
                      ? 'No nearby PMXT ladder snapshot was captured for this selected day, so only the price snapshot is available.'
                      : 'Historical orderbook-capacity overlay is currently wired for Madrid 36h PMXT replay first.'}
                  </p>
                )}
              </section>

              <section
                id="weather-workspace-signal-panel"
                role="tabpanel"
                aria-labelledby="weather-workspace-signal-tab"
                hidden={activeWorkspace !== 'signal'}
                className="weather-nearlock card rise weather-tab-panel"
              >
                <div className="weather-nearlock-header">
                  <div>
                    <div className="weather-nearlock-kicker">Near-Lock Console</div>
                    <h3>Late-settlement readout for the selected day</h3>
                    <p>
                      Modeled after Parity-style market boards, but focused on the last 6-18 hours: settlement-station freshness, price lag, and
                      whether the book still looked underpriced versus the final outcome.
                    </p>
                  </div>
                  <div className="weather-nearlock-badge">
                    <span className="eyebrow">Window</span>
                    <strong>{nearLockSummary.windowLabel}</strong>
                    <span>{nearLockSummary.triggerCount}/5 tweet checks passed</span>
                  </div>
                </div>

                <div className="weather-nearlock-scoreboard">
                  <div className="weather-nearlock-metric">
                    <span className="eyebrow">Lock Score</span>
                    <strong>{nearLockSummary.lockScore}</strong>
                    <span>{nearLockSummary.headline}</span>
                  </div>
                  <div className="weather-nearlock-metric">
                    <span className="eyebrow">Realized Edge</span>
                    <strong className={nearLockSummary.realizedEdge >= 0 ? 'pos' : 'neg'}>{fmtPct(nearLockSummary.realizedEdge, 1)}</strong>
                    <span>settlement payout minus price paid</span>
                  </div>
                  <div className="weather-nearlock-metric">
                    <span className="eyebrow">Feed Freshness</span>
                    <strong>{fmtMaybe(nearLockSummary.avgStale, 1)}m</strong>
                    <span>selected bucket average stale time</span>
                  </div>
                  <div className="weather-nearlock-metric">
                    <span className="eyebrow">Print Cadence</span>
                    <strong>{fmtMaybe(nearLockSummary.avgUpdates, 1)}</strong>
                    <span>updates captured in the last 6h</span>
                  </div>
                </div>

                <div className="weather-nearlock-grid">
                  <section className="weather-nearlock-panel">
                    <div className="eyebrow" style={{ marginBottom: 8 }}>
                      Trigger Checklist
                    </div>
                    <div className="weather-nearlock-checks">
                      {nearLockSummary.checklist.map((item) => (
                        <div key={item.label} className={`weather-nearlock-check ${item.pass ? 'pass' : 'fail'}`}>
                          <span>{item.label}</span>
                          <strong>{item.value}</strong>
                        </div>
                      ))}
                    </div>
                  </section>

                  <section className="weather-nearlock-panel">
                    <div className="eyebrow" style={{ marginBottom: 8 }}>
                      Bucket Ladder
                    </div>
                    <div className="weather-nearlock-table">
                      <div className="weather-nearlock-row weather-nearlock-row-head">
                        <span>Bucket</span>
                        <span>Px</span>
                        <span>Edge</span>
                        <span>Feed</span>
                        <span>Call</span>
                      </div>
                      {nearLockRows.slice(0, 6).map((row) => (
                        <div key={row.outcome.label} className={`weather-nearlock-row ${row.verdict}`}>
                          <span>
                            {row.outcome.label}
                            <div className="weather-chip-row" style={{ marginTop: 4 }}>
                              {row.selected ? <span className="weather-chip strong">bought</span> : null}
                              {row.isWinner ? <span className="weather-chip">winner</span> : null}
                            </div>
                          </span>
                          <span className="mono">{row.entryProb == null ? '-' : fmtPct(row.entryProb, 1)}</span>
                          <span className={`mono ${row.edgeToSettlement != null && row.edgeToSettlement >= 0 ? 'pos' : 'neg'}`}>
                            {row.edgeToSettlement == null ? '-' : fmtPct(row.edgeToSettlement, 1)}
                          </span>
                          <span className="mono">
                            {fmtMaybe(row.staleMinutes, 1)}m / {row.updates6h}
                          </span>
                          <span className={`weather-nearlock-tag ${row.verdict}`}>{row.note}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                </div>
              </section>

              <section
                id="weather-workspace-risk-panel"
                role="tabpanel"
                aria-labelledby="weather-workspace-risk-tab"
                hidden={activeWorkspace !== 'risk'}
                className="card weather-tab-panel"
                style={{ padding: 16 }}
              >
                <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, marginBottom: 8 }}>
                  <div>
                    <div className="eyebrow">Risk-Adjusted Strategy</div>
                    <h3 style={{ fontSize: 16 }}>What survives after guardrails?</h3>
                  </div>
                  <div className="muted" style={{ fontSize: 12, maxWidth: 440, textAlign: 'right' }}>
                    This view answers whether 36h is actually buyable, not just profitable on paper. Raw trades only count if they pass cost, freshness, cadence, adjacency, and pre-entry volatility checks.
                  </div>
                </header>
                <div className="weather-backtest-summary">
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Best Risk Hour</span>
                    <strong>{bestRiskAdjustedEntryHour == null ? '-' : `${bestRiskAdjustedEntryHour}h`}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Risk PnL</span>
                    <strong className={(strategyHourSummaryMap.get(selectedEntryHours ?? -1)?.gatedTotalPnl ?? 0) >= 0 ? 'pos' : 'neg'}>
                      {(strategyHourSummaryMap.get(selectedEntryHours ?? -1)?.gatedTotalPnl ?? 0).toFixed(3)}
                    </strong>
                    <span className="muted">selected entry hour after guardrails</span>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Live Trades</span>
                    <strong>{strategyHourSummaryMap.get(selectedEntryHours ?? -1)?.tradeCount ?? 0}</strong>
                    <span className="muted">passed as BUY</span>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Watch / Skip</span>
                    <strong>
                      {(strategyHourSummaryMap.get(selectedEntryHours ?? -1)?.watchCount ?? 0)}/
                      {(strategyHourSummaryMap.get(selectedEntryHours ?? -1)?.skipCount ?? 0)}
                    </strong>
                    <span className="muted">borderline / blocked</span>
                  </div>
                </div>
                <div style={{ marginTop: 14 }}>
                  <LineChart
                    series={strategyOverviewSeries}
                    markers={
                      selectedEvent
                        ? [
                            {
                              x: strategyEventRows.findIndex((row) => row.eventSlug === selectedEvent.eventSlug),
                              y: strategyEventRows.find((row) => row.eventSlug === selectedEvent.eventSlug)?.cumulativeGatedPnl ?? 0,
                              color: CHART.text,
                              label: 'selected',
                            },
                          ].filter((marker) => marker.x >= 0)
                        : []
                    }
                    height={260}
                    xFormat={(value) => {
                      const row = strategyEventRows[Math.round(value)];
                      return row ? fmtDateShort(row.date) : '';
                    }}
                    yFormat={(value) => value.toFixed(2)}
                  />
                </div>
              </section>

              <section className="card weather-tab-panel" hidden={activeWorkspace !== 'risk'} style={{ padding: 16 }}>
                <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, marginBottom: 8 }}>
                  <div>
                    <div className="eyebrow">Execution Reality Check</div>
                    <h3 style={{ fontSize: 16 }}>Conservative scenario after friction and stale-data filters</h3>
                  </div>
                  <div className="muted" style={{ fontSize: 12, maxWidth: 440, textAlign: 'right' }}>
                    Conservative PnL = raw entry cost + `slippage/leg` + `fee/leg`, and the trade is skipped if any selected bucket violates `max stale min` or `min updates 6h`.
                  </div>
                </header>
                <div className="weather-backtest-summary">
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Raw Cum PnL</span>
                    <strong className={executionSummary.rawTotal >= 0 ? 'pos' : 'neg'}>{executionSummary.rawTotal.toFixed(3)}</strong>
                    <span className="muted">same as current backtest</span>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Conservative Cum PnL</span>
                    <strong className={executionSummary.conservativeTotal >= 0 ? 'pos' : 'neg'}>{executionSummary.conservativeTotal.toFixed(3)}</strong>
                    <span className="muted">after friction and filters</span>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Blocked Trades</span>
                    <strong>{executionSummary.blockedTrades}</strong>
                    <span className="muted">out of {entrySummary.tradedCount}</span>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Max Drawdown</span>
                    <strong className={executionSummary.conservativeDrawdown > 0 ? 'neg' : ''}>{executionSummary.conservativeDrawdown.toFixed(3)}</strong>
                    <span className="muted">conservative curve</span>
                  </div>
                </div>
                <div className="weather-capacity-grid" style={{ marginTop: 10 }}>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Max Concurrent Capital</span>
                    <strong>{executionSummary.maxConcurrentCapital.toFixed(3)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Avg Conservative Cost</span>
                    <strong>{fmtPct(executionSummary.avgConservativeCost, 1)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Passed Trades</span>
                    <strong>{executionSummary.passedTrades}</strong>
                  </div>
                </div>
                <div style={{ marginTop: 14 }}>
                  <LineChart
                    series={executionOverviewSeries}
                    markers={
                      selectedEvent
                        ? [
                            {
                              x: executionRows.findIndex((row) => row.eventSlug === selectedEvent.eventSlug),
                              y: executionRows.find((row) => row.eventSlug === selectedEvent.eventSlug)?.cumulativeConservativePnl ?? 0,
                              color: CHART.text,
                              label: 'selected',
                            },
                          ].filter((marker) => marker.x >= 0)
                        : []
                    }
                    height={260}
                    xFormat={(value) => {
                      const row = executionRows[Math.round(value)];
                      return row ? fmtDateShort(row.date) : '';
                    }}
                    yFormat={(value) => value.toFixed(2)}
                  />
                </div>
              </section>

              <section
                id="weather-workspace-audit-panel"
                role="tabpanel"
                aria-labelledby="weather-workspace-audit-tab"
                hidden={activeWorkspace !== 'audit'}
                className="card weather-tab-panel"
                style={{ padding: 16 }}
              >
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Event Timeline
                </div>
                <div className="weather-event-table-wrap">
                  <table className="weather-event-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Verdict</th>
                        <th>Risk PnL</th>
                        <th>Risk Cum</th>
                        <th>Raw</th>
                        <th>Cons.</th>
                        <th>Cons. Cum</th>
                        <th>Hit</th>
                        <th>Selection</th>
                        <th>Raw Cost</th>
                        <th>Cons. Cost</th>
                        <th>Policy</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...executionRows].reverse().map((row) => {
                        const strategyRow = strategyEventRows.find((item) => item.eventSlug === row.eventSlug);
                        const active = row.eventSlug === selectedEvent.eventSlug;
                        return (
                          <tr
                            key={row.eventSlug}
                            className={active ? 'active' : undefined}
                            onClick={() => setSelectedEventSlug(row.eventSlug)}
                            title={row.blockReasons.join(' | ') || 'passed policy'}
                          >
                            <td className="mono">{fmtDateShort(row.date)}</td>
                            <td>{strategyRow?.verdict ?? '-'}</td>
                            <td className={`mono ${(strategyRow?.gatedPnl ?? 0) >= 0 ? 'pos' : 'neg'}`}>{(strategyRow?.gatedPnl ?? 0).toFixed(3)}</td>
                            <td className={`mono ${(strategyRow?.cumulativeGatedPnl ?? 0) >= 0 ? 'pos' : 'neg'}`}>{(strategyRow?.cumulativeGatedPnl ?? 0).toFixed(3)}</td>
                            <td className={`mono ${row.rawPnl >= 0 ? 'pos' : 'neg'}`}>{row.rawPnl.toFixed(3)}</td>
                            <td className={`mono ${row.conservativePnl >= 0 ? 'pos' : 'neg'}`}>{row.conservativePnl.toFixed(3)}</td>
                            <td className={`mono ${row.cumulativeConservativePnl >= 0 ? 'pos' : 'neg'}`}>{row.cumulativeConservativePnl.toFixed(3)}</td>
                            <td>{row.didHit ? 'Yes' : 'No'}</td>
                            <td>{row.selectedLabels.join(' + ') || 'skip'}</td>
                            <td className="mono">{fmtPct(row.selectedProbabilitySum, 1)}</td>
                            <td className="mono">{fmtPct(row.conservativeCost, 1)}</td>
                            <td>{row.blockedByPolicy ? row.blockReasons.join(', ') : 'pass'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>

              <div className="weather-research-grid">
                <section className="card weather-tab-panel" hidden={activeWorkspace !== 'overview'} style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Alpha Notes
                  </div>
                  <div className="weather-note-list">
                    {alphaNotes.map((note) => (
                      <p key={note} className="weather-note">
                        {note}
                      </p>
                    ))}
                  </div>
                </section>

                <section className="card weather-tab-panel" hidden={activeWorkspace !== 'liquidity'} style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Capacity & Friction
                  </div>
                  <div className="weather-capacity-grid">
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Selected Vol</span>
                      <strong>{fmtCompact(capacitySummary.selectedVolume)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">24h Vol</span>
                      <strong>{fmtCompact(capacitySummary.selectedVolume24hr)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Liquidity</span>
                      <strong>{fmtCompact(capacitySummary.selectedLiquidity)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Median Spread</span>
                      <strong>{capacitySummary.medianSpread == null ? '-' : fmtPct(capacitySummary.medianSpread / 100, 2)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Avg Stale Min</span>
                      <strong>{fmtMaybe(capacitySummary.avgStaleMinutes, 1)}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">Pre-entry 6h Move</span>
                      <strong>{selectedResearchRows.length > 0 ? fmtPct(average(selectedResearchRows.map((row) => row.move6hBeforeEntry)) ?? 0, 1) : '-'}</strong>
                    </div>
                    <div className="weather-capacity-item">
                      <span className="eyebrow">1h Move</span>
                      <strong>{capacitySummary.avgMove1h == null ? '-' : fmtPct(capacitySummary.avgMove1h, 1)}</strong>
                    </div>
                  </div>
                  <p className="muted weather-footnote">
                    Volume, liquidity, min size, and spread are rough market-capacity proxies from Polymarket market payloads. Staleness, updates, and 1h move are reconstructed from price history at the entry timestamp and are the better slippage warning signals here.
                  </p>
                </section>
              </div>

              {dataset.citySlug === 'madrid' && madridDailyBuyRows.length > 0 ? (
                <section className="card weather-tab-panel" hidden={activeWorkspace !== 'liquidity'} style={{ padding: 16 }}>
                  <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, marginBottom: 8 }}>
                    <div>
                      <div className="eyebrow">36h Daily Buy Points</div>
                      <h3 style={{ fontSize: 16 }}>EDT verification sheet for the PMXT Madrid replay</h3>
                    </div>
                    <div className="muted" style={{ fontSize: 12, maxWidth: 440, textAlign: 'right' }}>
                      These rows are the exact daily buy calls for the 36h Madrid strategy, converted to New York time so you can verify them directly in the market UI.
                    </div>
                  </header>
                  <div className="weather-event-table-wrap">
                    <table className="weather-event-table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>EDT Buy Time</th>
                          <th>Buy</th>
                          <th>Paid</th>
                          <th>Snapshot Size</th>
                          <th>Size +1c</th>
                          <th>Book Age</th>
                          <th>PnL</th>
                          <th>Hit</th>
                          <th>Winner</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...madridDailyBuyRows].reverse().map((row) => {
                          const depthRows = madridOrderbookByDate.get(row.date) ?? [];
                          const snapshotSize = depthRows.reduce((acc, item) => acc + (item.snapshotSize ?? 0), 0);
                          const plus1c = depthRows.some((item) => item.cumSizePlus1c != null)
                            ? depthRows.reduce((acc, item) => acc + (item.cumSizePlus1c ?? 0), 0)
                            : null;
                          const bookAge = average(depthRows.map((item) => item.bookAgeMinutes));
                          return (
                          <tr key={`${row.date}-${row.entryTimeEdt}`}>
                            <td className="mono">{fmtDateShort(row.date)}</td>
                            <td className="mono">{row.entryTimeEdt}</td>
                            <td>{row.selection}</td>
                            <td className="mono">{fmtPct(row.probabilityPaid, 1)}</td>
                            <td className="mono">{depthRows.length > 0 ? fmtCompact(snapshotSize, 1) : '-'}</td>
                            <td className="mono">{plus1c == null ? '-' : fmtCompact(plus1c, 1)}</td>
                            <td className="mono">{fmtMaybe(bookAge, 1)}</td>
                            <td className={`mono ${row.pnl >= 0 ? 'pos' : 'neg'}`}>{row.pnl.toFixed(3)}</td>
                            <td>{row.didHit ? 'Yes' : 'No'}</td>
                            <td>{row.winnerLabel ?? '-'}</td>
                          </tr>
                        )})}
                      </tbody>
                    </table>
                  </div>
                  {dataset.timezoneNote ? (
                    <p className="muted weather-footnote">{dataset.timezoneNote}</p>
                  ) : null}
                </section>
              ) : null}

              <section className="card weather-tab-panel" hidden={activeWorkspace !== 'signal'} style={{ padding: 16 }}>
                <header style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 16, marginBottom: 8 }}>
                  <div>
                    <div className="eyebrow">Price History</div>
                    <h3 style={{ fontSize: 16 }}>Outcome probabilities with marked buy points</h3>
                  </div>
                  <div className="muted" style={{ fontSize: 12 }}>
                    Vertical line marks the entry timestamp. Colored circles mark bought buckets.
                  </div>
                </header>
                <LineChart
                  series={chartSeries}
                  markers={chartMarkers}
                  rules={chartRules}
                  height={340}
                  xFormat={fmtDateTime}
                  yFormat={(value) => fmtPct(value, 0)}
                />
              </section>

              <div className="weather-detail-grid weather-tab-panel" hidden={activeWorkspace !== 'signal'}>
                <section className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Why It Bought
                  </div>
                  <p style={{ margin: 0, fontSize: 14 }}>{selectedRun.reason}</p>
                  <div className="weather-chip-row" style={{ marginTop: 12 }}>
                    {selectedRun.selectedLabels.map((label, index) => (
                      <span key={label} className="weather-chip strong">
                        {label} @ {(selectedRun.selectedPrices[index] ?? 0).toFixed(3)}
                      </span>
                    ))}
                    {selectedRun.selectedLabels.length === 0 ? <span className="weather-chip">No trade</span> : null}
                  </div>
                </section>

                <section className="card" style={{ padding: 16 }}>
                  <div className="eyebrow" style={{ marginBottom: 8 }}>
                    Same Day, Other Entry Hours
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    {selectedEvent.runs.map((run) => {
                      const active = run.entryHours === selectedRun.entryHours;
                      return (
                        <button
                          key={run.entryHours}
                          type="button"
                          className={`weather-run-row ${active ? 'active' : ''}`}
                          onClick={() => setSelectedEntryHours(run.entryHours)}
                        >
                          <span className="mono">{run.entryHours}h</span>
                          <span>{run.selectedLabels.join(' + ') || 'skip'}</span>
                          <span className={`mono ${run.pnl >= 0 ? 'pos' : 'neg'}`}>{run.pnl.toFixed(3)}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              </div>

              <section className="card weather-tab-panel" hidden={activeWorkspace !== 'liquidity'} style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Entry Snapshot & Liquidity Proxies
                </div>
                <table className="weather-outcome-table">
                  <thead>
                    <tr>
                      <th>Outcome</th>
                      <th>Entry Prob</th>
                      <th>Stale Min</th>
                      <th>Updates 6h</th>
                      <th>1h Move</th>
                      <th>Vol</th>
                      <th>Spread</th>
                      <th>Min Size</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {researchRows.map((row) => {
                      const { outcome } = row;
                      return (
                        <tr key={outcome.label}>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span
                                style={{
                                  width: 10,
                                  height: 10,
                                  borderRadius: 999,
                                  background: row.selected
                                    ? COMPARE_COLORS[selectedRun.selectedLabels.indexOf(outcome.label) % COMPARE_COLORS.length]
                                    : outcome.isWinner
                                      ? CHART.position
                                      : CHART.price,
                                }}
                              />
                              {outcome.label}
                            </div>
                          </td>
                          <td className="mono">{row.entryProb == null ? '-' : fmtPct(row.entryProb, 1)}</td>
                          <td className="mono">{fmtMaybe(row.staleMinutes, 1)}</td>
                          <td className="mono">{row.updates6h}</td>
                          <td className="mono">{row.move1hAfterEntry == null ? '-' : fmtPct(row.move1hAfterEntry, 1)}</td>
                          <td className="mono">{fmtCompact(outcome.marketStats.volume)}</td>
                          <td className="mono">
                            {outcome.marketStats.spread == null ? '-' : fmtPct(outcome.marketStats.spread / 100, 2)}
                          </td>
                          <td className="mono">{fmtMaybe(outcome.marketStats.orderMinSize, 0)}</td>
                          <td>
                            <div className="weather-chip-row">
                              {row.selected ? <span className="weather-chip strong">bought</span> : null}
                              {outcome.isWinner ? <span className="weather-chip">winner</span> : null}
                              {outcome.marketStats.rewardsMinSize != null ? (
                                <span className="weather-chip">reward min {fmtMaybe(outcome.marketStats.rewardsMinSize, 0)}</span>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="muted weather-footnote">
                  `Vol`, `Spread`, and `Min Size` are not true historical order-book snapshots. Use them as market-cap proxies, then lean more heavily on `Stale Min`, `Updates 6h`, and `1h Move` when deciding whether the backtest is realistically tradable.
                </p>
              </section>

              <section className="card weather-tab-panel" hidden={activeWorkspace !== 'liquidity'} style={{ padding: 16 }}>
                <div className="eyebrow" style={{ marginBottom: 8 }}>
                  Execution Notes
                </div>
                <div className="weather-exec-grid">
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Next Print Delay</span>
                    <strong>{fmtMaybe(capacitySummary.nextPrintDelayMinutes, 1)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Reward Min Size</span>
                    <strong>{fmtMaybe(capacitySummary.minRewardSize, 0)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Order Min Size</span>
                    <strong>{fmtMaybe(capacitySummary.minOrderSize, 0)}</strong>
                  </div>
                  <div className="weather-capacity-item">
                    <span className="eyebrow">Prob Sum</span>
                    <strong>{fmtPct(selectedRun.selectedProbabilitySum, 1)}</strong>
                  </div>
                </div>
              </section>
            </div>
          ) : status === 'loading' ? (
            <div className="card" style={{ padding: 24 }}>
              <div className="eyebrow">Loading</div>
              <h2 style={{ marginTop: 6 }}>Preparing weather research workspace</h2>
            </div>
          ) : (
            <div className="card" style={{ padding: 24 }}>
              <div className="eyebrow" style={{ color: 'var(--neg)' }}>
                Failed to load
              </div>
              <p className="mono neg" style={{ marginBottom: 0 }}>
                {error}
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
