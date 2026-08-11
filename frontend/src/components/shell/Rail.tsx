import type { Mode, WorkspaceView } from '../../lib/selection';

function modes(): { id: Mode; label: string; hint: string }[] {
  return [
    { id: 'simulate', label: 'SIMULATE', hint: 'Run the event live' },
    { id: 'investigate', label: 'INVESTIGATE', hint: 'Examine flow and capacity' },
    { id: 'intervene', label: 'INTERVENE', hint: 'Act on the system' },
    { id: 'compare', label: 'COMPARE', hint: 'Test against a counterfactual' },
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
    <nav aria-label="Operational mode" className="hidden w-52 shrink-0 flex-col border-r border-od-line bg-od-panel md:flex">
      <div className="border-b border-od-line px-4 pb-3 pt-4">
        <div className="font-display text-[15px] font-bold tracking-[0.32em] text-od-ink">
          CROWD·FLOW
        </div>
        <div className="mt-0.5 text-[10px] uppercase tracking-[0.2em] text-od-muted">
          Crowd Operations
        </div>
      </div>

      <div className="flex-1 space-y-1 px-3 pt-4" aria-label="Primary modes">
        {modes().map((m) => (
          <button
            key={m.id}
            onClick={() => onView(m.id)}
            aria-pressed={view === m.id}
            className={`rail-btn w-full ${view === m.id ? 'is-active' : ''}`}
            title={m.hint}
          >
            <span>{m.label}</span>
          </button>
        ))}

        <div className="px-2 pb-1 pt-4 text-[9px] uppercase tracking-[0.22em] text-od-muted">Configure</div>
        <button onClick={() => onView('scenarios')} className={`rail-btn w-full ${view === 'scenarios' ? 'is-active' : ''}`}>
          <span>SCENARIOS</span>
        </button>
        <button onClick={() => onView('venues')} className={`rail-btn w-full ${view === 'venues' ? 'is-active' : ''}`}>
          <span>VENUES</span>
        </button>
        <button onClick={() => onView('settings')} className={`rail-btn w-full ${view === 'settings' ? 'is-active' : ''}`}>
          <span>SETTINGS</span>
        </button>
      </div>

      <div className="flex items-center justify-between border-t border-od-line p-3">
        <span className="inline-flex items-center gap-2 text-[9px] uppercase tracking-[0.18em] text-od-muted">
          <span className={`status-dot ${backendOk === false ? 'is-danger' : backendOk ? 'is-ok' : 'is-scan'}`} />
          {backendOk === false ? 'Backend offline' : backendOk ? 'Backend live' : 'Scanning'}
        </span>
        <span className="text-[9px] uppercase tracking-[0.18em] text-od-muted">v2</span>
      </div>
    </nav>
  );
}