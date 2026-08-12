import { Boxes, Crosshair, Eye, FolderKanban, GitCompareArrows, Map as MapIcon, Settings, Zap } from 'lucide-react';
import type { Mode, WorkspaceView } from '../../lib/selection';

function modes(): { id: Mode; label: string; hint: string; Icon: typeof Eye }[] {
  return [
    { id: 'simulate', label: 'OBSERVE', hint: 'Watch the venue evolve', Icon: Eye },
    { id: 'investigate', label: 'UNDERSTAND', hint: 'Examine flow, capacity and risk', Icon: Crosshair },
    { id: 'intervene', label: 'ACT', hint: 'Perturb the world and watch the response', Icon: Zap },
    { id: 'compare', label: 'DECIDE', hint: 'Compare against a counterfactual', Icon: GitCompareArrows },
  ];
}

export default function Rail({
  view,
  onView,
  backendOk,
}: {
  view: WorkspaceView;
  onView: (v: WorkspaceView) => void;
  backendOk: boolean | null;
}) {
  return (
    <nav
      aria-label="Operational mode"
      className="hidden w-14 shrink-0 flex-col border-r border-od-line bg-od-panel md:flex"
    >
      <div className="border-b border-od-line px-2 py-3 text-center">
        <div className="font-display text-[13px] font-bold tracking-tighter text-od-ink" title="CROWD·FLOW">
          C·F
        </div>
      </div>

      <div className="flex-1 space-y-1 px-2 pt-4" aria-label="Primary modes">
        {modes().map((m) => (
          <button
            key={m.id}
            onClick={() => onView(m.id)}
            aria-pressed={view === m.id}
            aria-label={m.label}
            className={`rail-btn rail-icon w-full ${view === m.id ? 'is-active' : ''}`}
            title={`${m.label} — ${m.hint}`}
          >
            <m.Icon className="h-4 w-4 shrink-0" />
          </button>
        ))}

        <button
          onClick={() => onView('twin3d')}
          aria-label="3D Twin"
          className={`rail-btn rail-icon w-full ${view === 'twin3d' ? 'is-active' : ''}`}
          title="3D venue twin — interactive spatial model"
        >
          <Boxes className="h-4 w-4 shrink-0" />
        </button>

        <div className="px-2 pb-1 pt-4 text-center text-[9px] uppercase tracking-[0.18em] text-od-muted" title="Configure">
          —·—
        </div>
        <button
          onClick={() => onView('scenarios')}
          aria-label="Scenarios"
          className={`rail-btn rail-icon w-full ${view === 'scenarios' ? 'is-active' : ''}`}
          title="Scenarios"
        >
          <FolderKanban className="h-4 w-4 shrink-0" />
        </button>
        <button
          onClick={() => onView('venues')}
          aria-label="Venues"
          className={`rail-btn rail-icon w-full ${view === 'venues' ? 'is-active' : ''}`}
          title="Venues"
        >
          <MapIcon className="h-4 w-4 shrink-0" />
        </button>
        <button
          onClick={() => onView('settings')}
          aria-label="Settings"
          className={`rail-btn rail-icon w-full ${view === 'settings' ? 'is-active' : ''}`}
          title="Settings"
        >
          <Settings className="h-4 w-4 shrink-0" />
        </button>
      </div>

      <div className="flex flex-col items-center gap-2 border-t border-od-line py-3">
        <span
          className={`status-dot ${backendOk === false ? 'is-danger' : backendOk ? 'is-ok' : 'is-scan'}`}
          title={backendOk === false ? 'Backend offline' : backendOk ? 'Backend live' : 'Scanning'}
        />
        <span className="text-[9px] uppercase tracking-[0.18em] text-od-muted">v2</span>
      </div>
    </nav>
  );
}