import { useEffect, useState } from 'react';
import { Dashboard } from './pages/Dashboard';
import { WeatherResearchPage } from './pages/WeatherResearchPage';
import type { AppMode } from './components/TopBar';

export default function App() {
  const [mode, setMode] = useState<AppMode>(() => {
    const raw = localStorage.getItem('pm-app-mode');
    return raw === 'dashboard' || raw === 'weather' ? raw : 'weather';
  });

  useEffect(() => {
    localStorage.setItem('pm-app-mode', mode);
  }, [mode]);

  return mode === 'weather' ? (
    <WeatherResearchPage mode={mode} onModeChange={setMode} />
  ) : (
    <Dashboard mode={mode} onModeChange={setMode} />
  );
}
