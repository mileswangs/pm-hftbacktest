import { useMemo, useState } from 'react';
import type { AdapterKind, BacktestConfig } from '../services/types';
import { getService } from '../services';
import { useBacktestRuns } from '../hooks/useBacktestRuns';
import { TopBar } from '../components/TopBar';
import type { AppMode } from '../components/TopBar';
import { HistorySidebar } from '../components/HistorySidebar';
import { ConfigPanel } from '../components/ConfigPanel';
import { ResultsPanel } from '../components/ResultsPanel';
import { CompareView } from '../components/CompareView';
import './Dashboard.css';

export function Dashboard({
  mode,
  onModeChange,
}: {
  mode: AppMode;
  onModeChange: (mode: AppMode) => void;
}) {
  const [adapter, setAdapter] = useState<AdapterKind>('mock');
  const service = useMemo(() => getService(adapter), [adapter]);
  const bt = useBacktestRuns(service);
  const [comparing, setComparing] = useState(false);

  const showCompare = comparing && bt.compareRuns.length === 2;

  function handleRun(config: BacktestConfig) {
    setComparing(false);
    bt.run(config).catch(() => {
      /* error surfaced via hook state */
    });
  }

  return (
    <div className="shell">
      <TopBar mode={mode} onModeChange={onModeChange} adapter={adapter} onAdapterChange={setAdapter} />
      <main className="grid">
        <div className="col-history">
          <HistorySidebar
            runs={bt.runs}
            activeId={bt.activeId}
            compareIds={bt.compareIds}
            onSelect={bt.selectRun}
            onToggleCompare={bt.toggleCompare}
            onCompare={() => setComparing(true)}
          />
        </div>

        <div className="col-config">
          <ConfigPanel running={bt.status === 'running'} onRun={handleRun} />
        </div>

        <div className="col-results">
          {showCompare ? (
            <CompareView
              runs={bt.compareRuns}
              onClose={() => {
                setComparing(false);
                bt.clearCompare();
              }}
            />
          ) : (
            <ResultsPanel status={bt.status} error={bt.error} result={bt.activeRun} />
          )}
        </div>
      </main>
    </div>
  );
}
