import { useEffect, useState } from 'react';
import { Dashboard } from './pages/Dashboard';
import { WeatherResearchPage } from './pages/WeatherResearchPage';
import { MetarStudyPage } from './pages/MetarStudyPage';
import type { AppMode } from './components/TopBar';

export default function App() {
  const [mode, setMode] = useState<AppMode>(() => {
    const raw = localStorage.getItem('pm-app-mode');
    return raw === 'dashboard' || raw === 'weather' || raw === 'metar' ? raw : 'weather';
  });

  useEffect(() => {
    localStorage.setItem('pm-app-mode', mode);
  }, [mode]);

  if (mode === 'weather') {
    return <WeatherResearchPage mode={mode} onModeChange={setMode} />;
  }
  if (mode === 'metar') {
    return <MetarStudyPage mode={mode} onModeChange={setMode} />;
  }
  return <Dashboard mode={mode} onModeChange={setMode} />;
}
