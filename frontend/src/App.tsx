import { useCallback, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import Rail from './components/shell/Rail';
import Instrument from './components/workspace/Instrument';
import SettingsScreen from './components/shell/SettingsScreen';
import VenueBuilderView from './views/VenueBuilderView';
import ScenarioBuilderView from './views/ScenarioBuilderView';
import { SimulationProvider, useSimulation } from './store/SimulationContext';
import type { Mode, WorkspaceView } from './lib/selection';
import './App.css';

function SecondaryFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex h-full flex-col bg-background">
      <div className="flex items-center justify-between border-b border-outline-variant px-5 py-3">
        <div>
          <h1 className="font-display-xl font-extrabold uppercase tracking-tighter leading-none text-[clamp(20px,2.6vw,30px)]">
            {title}
          </h1>
          <p className="mt-1 text-[10px] uppercase tracking-[0.24em] text-secondary">CROWDFLOW COMMAND CENTRE</p>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin p-4 md:p-6">{children}</div>
    </div>
  );
}

function Shell() {
  const { backendOnline, error, clearError, theme, toggleTheme } = useSimulation();
  const [view, setView] = useState<WorkspaceView>('simulate');
  const go = useCallback((v: WorkspaceView) => setView(v), []);
  const mode: Mode = ['simulate', 'investigate', 'intervene', 'compare'].includes(view)
    ? (view as Mode)
    : 'simulate';
  const isSecondary = view === 'scenarios' || view === 'venues' || view === 'settings';

  return (
    <div className="flex h-screen w-full overflow-hidden bg-od-canvas">
      <Rail view={view} onView={go} backendOk={backendOnline} />

      <main className="relative flex min-w-0 flex-1 flex-col">
        {error && (
          <div
            role="alert"
            className="flex shrink-0 items-center justify-between gap-2 bg-od-danger px-4 py-1.5 text-[10px] uppercase tracking-[0.14em] font-bold text-[var(--od-canvas)]"
          >
            <span className="flex items-center gap-2 truncate">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {error}
            </span>
            <button onClick={clearError} aria-label="Dismiss error" className="cursor-pointer px-1 hover:opacity-70">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
        {backendOnline === false && (
          <div className="flex shrink-0 items-center gap-2 bg-od-danger px-4 py-1.5 text-[10px] uppercase tracking-[0.16em] font-bold text-[var(--od-canvas)]">
            <AlertTriangle className="h-3.5 w-3.5" />
            Backend unreachable — start it with <code className="bg-black/20 px-1">uvicorn app.main:app --reload</code>
          </div>
        )}

        <div className="min-h-0 flex-1">
          {view === 'scenarios' && (
            <SecondaryFrame title="Scenarios">
              <ScenarioBuilderView />
            </SecondaryFrame>
          )}
          {view === 'venues' && (
            <SecondaryFrame title="Venues">
              <VenueBuilderView />
            </SecondaryFrame>
          )}
          {view === 'settings' && <SettingsScreen theme={theme} onToggleTheme={toggleTheme} backendOnline={backendOnline} go={go} />}
          {!isSecondary && <Instrument mode={mode} onMode={go} />}
        </div>

        {/* mobile mode bar */}
        {!isSecondary && (
          <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-t border-od-line bg-od-panel px-2 py-1 md:hidden">
            {(['simulate', 'investigate', 'intervene', 'compare'] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => go(m)}
                aria-pressed={mode === m}
                className={`rail-btn ${mode === m ? 'is-active' : ''}`}
              >
                {m.toUpperCase()}
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <SimulationProvider>
      <Shell />
    </SimulationProvider>
  );
}