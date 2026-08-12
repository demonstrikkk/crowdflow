import { Suspense, lazy, useCallback, useState } from 'react';
import { AlertTriangle, ArrowLeft, X } from 'lucide-react';
import Rail from './components/shell/Rail';
import Instrument from './components/workspace/Instrument';
import SettingsScreen from './components/shell/SettingsScreen';
import VenueBuilderView from './views/VenueBuilderView';
import ScenarioBuilderView from './views/ScenarioBuilderView';
import CreateTwinView from './views/CreateTwinView';
import BlueprintReviewView from './views/BlueprintReviewView';
import { SimulationProvider, useSimulation } from './store/SimulationContext';
import type { Mode, WorkspaceView } from './lib/selection';
import './App.css';

const Venue3DView = lazy(() => import('./components/workspace/Venue3DView'));

function SecondaryFrame({
  title,
  children,
  onBack,
  flush = false,
}: {
  title: string;
  children: React.ReactNode;
  onBack: () => void;
  flush?: boolean;
}) {
  return (
    <div className="flex h-full flex-col bg-od-canvas">
      <div className="flex shrink-0 items-center gap-4 border-b border-od-line bg-od-panel px-4 py-3">
        <button
          onClick={onBack}
          aria-label="Back to operations"
          title="Back to the workspace"
          className="btn btn-ghost"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        <div className="min-w-0">
          <h1 className="font-display text-[15px] font-bold uppercase tracking-[0.18em] text-od-ink leading-none">
            {title}
          </h1>
          <p className="mt-1 text-[9px] uppercase tracking-[0.24em] text-od-muted">CrowdFlow command centre</p>
        </div>
        <span className="flex-1" />
        <span className="chip">
          <span className="status-dot is-ok" />
          {title} catalogue
        </span>
      </div>
      <div className={`min-h-0 flex-1 ${flush ? '' : 'overflow-y-auto scrollbar-thin p-4 md:p-6'}`}>{children}</div>
    </div>
  );
}

function Shell() {
  const { backendOnline, error, clearError, theme, toggleTheme, venue } = useSimulation();
  const [view, setView] = useState<WorkspaceView>('simulate');
  const go = useCallback((v: WorkspaceView) => setView(v), []);
  const mode: Mode = ['simulate', 'investigate', 'intervene', 'compare'].includes(view)
    ? (view as Mode)
    : 'simulate';
  const isSecondary = view === 'scenarios' || view === 'venues' || view === 'settings' || view === 'twin3d' || view === 'blueprint';

  const [blueprintFile, setBlueprintFile] = useState<File | null>(null);
  const [blueprintBackTo, setBlueprintBackTo] = useState<WorkspaceView>('simulate');
  const openBlueprint = useCallback(
    (file: File) => {
      setBlueprintFile(file);
      setBlueprintBackTo(view);
      setView('blueprint');
    },
    [view],
  );
  const closeBlueprint = useCallback(() => {
    setBlueprintFile(null);
    go(blueprintBackTo);
  }, [blueprintBackTo, go]);
  const openTwinFromBlueprint = useCallback(() => {
    setBlueprintFile(null);
    go('twin3d');
  }, [go]);

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
            <SecondaryFrame title="Scenarios" onBack={() => go('simulate')}>
              <ScenarioBuilderView />
            </SecondaryFrame>
          )}
          {view === 'venues' && (
            <SecondaryFrame title="Venues" onBack={() => go('simulate')}>
              <VenueBuilderView onReviewBlueprint={openBlueprint} />
            </SecondaryFrame>
          )}
          {view === 'blueprint' && (
            <BlueprintReviewView
              initialFile={blueprintFile}
              onOpenTwin={openTwinFromBlueprint}
              onExit={closeBlueprint}
            />
          )}
          {view === 'twin3d' && (
            <SecondaryFrame title="3D Twin" onBack={() => go('simulate')} flush>
              <Suspense
                fallback={
                  <div className="flex h-full w-full items-center justify-center bg-od-canvas">
                    <span className="text-[10px] uppercase tracking-[0.24em] text-od-muted">
                      Loading 3D engine…
                    </span>
                  </div>
                }
              >
                <Venue3DView />
              </Suspense>
            </SecondaryFrame>
          )}
          {view === 'settings' && <SettingsScreen theme={theme} onToggleTheme={toggleTheme} backendOnline={backendOnline} go={go} />}
          {!isSecondary && (venue ? <Instrument mode={mode} onMode={go} /> : <CreateTwinView onReady={() => go('simulate')} onReviewBlueprint={openBlueprint} />)}
        </div>

        {/* mobile mode bar */}
        {!isSecondary && venue && (
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