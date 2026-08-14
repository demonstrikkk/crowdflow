import { AlertTriangle, X } from 'lucide-react';
import { SimulationProvider, useSimulation } from './store/SimulationContext';
import { AutoLoadBridge } from './components/workspace/AutoLoadBridge';
import WorldScreen from './components/world/WorldScreen';
import './App.css';

function Shell() {
  const { error, clearError, backendOnline } = useSimulation();

  return (
    <div className="h-screen w-full overflow-hidden bg-od-canvas">
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
          Backend unreachable — start it with <code className="bg-black/20 px-1">uvicorn app.main:app --app-dir backend</code>
        </div>
      )}

      <WorldScreen />
    </div>
  );
}

export default function App() {
  return (
    <SimulationProvider>
      <AutoLoadBridge />
      <Shell />
    </SimulationProvider>
  );
}