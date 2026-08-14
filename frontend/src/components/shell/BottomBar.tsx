import type { ReactNode } from 'react';
import { useSimulation } from '../../store/SimulationContext';
import type { WorldTool, WorldView } from '../../lib/nav';

const PHASE_TONE: Record<string, string> = {
  ENTRY: 'var(--od-ok)',
  PEAK: 'var(--od-warn)',
  INTERVAL: 'var(--od-muted)',
  EXIT_SURGE: 'var(--od-danger)',
};

function predRef(ref: string): string {
  const g = ref.replace('GATE_', 'G').replace(/_/g, ' ');
  return g;
}

interface BottomBarProps {
  tools: { id: WorldTool; label: string; icon: ReactNode; blurb: string }[];
  tool: WorldTool;
  onToolChange: (t: WorldTool) => void;
  view: WorldView;
  onViewChange: (v: WorldView) => void;
  canEnterVenue: boolean;
  onJumpToMinute: (minute: number) => void;
  draftPending: boolean;
  onApplyDraft: () => void;
  onClearDraft: () => void;
  cfSimId: string | null;
  onApplyCf: () => void;
  onDiscardCf: () => void;
}

export default function BottomBar({
  tools,
  tool,
  onToolChange,
  view,
  onViewChange,
  canEnterVenue,
  onJumpToMinute,
  draftPending,
  onApplyDraft,
  onClearDraft,
  cfSimId,
  onApplyCf,
  onDiscardCf,
}: BottomBarProps) {
  const s = useSimulation();
  const predictions = s.displayedSim?.world?.predictions ?? [];
  const phases = s.scenario?.event_phases ?? [];
  const blurb = tools.find((m) => m.id === tool)?.blurb ?? '';

  return (
    <footer className="shrink-0 border-t border-od-line bg-od-panel/80 px-3 py-2 backdrop-blur">
      {/* row 1 — predictions + event states */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="sec-label">Predictions</span>
        {predictions.length > 0 ? (
          <div className="flex min-w-0 flex-wrap items-center gap-1">
            {predictions.slice(0, 8).map((p) => (
              <span
                key={p.id}
                className="chip !cursor-default !py-0.5"
                title={`${p.ref} ${p.severity} in ~${p.in_minutes.toFixed(1)} min`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    p.severity === 'CRITICAL' || p.severity === 'HIGH'
                      ? 'bg-od-danger'
                      : p.severity === 'ELEVATED'
                        ? 'bg-od-warn'
                        : 'bg-od-ok'
                  }`}
                />
                PREDICTION - {predRef(p.ref)}
              </span>
            ))}
          </div>
        ) : (
          <span className="text-[9px] uppercase tracking-[0.14em] text-od-muted">— none active</span>
        )}

        <span className="h-4 w-px bg-od-line" />

        <span className="sec-label">Event state</span>
        <div className="flex items-center gap-1">
          {phases.map((p) => (
            <button
              key={p.name}
              className="chip !py-0.5"
              title={`Jump to ${p.name} start (${p.start_minute} min)`}
              onClick={() => onJumpToMinute(p.start_minute)}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: PHASE_TONE[p.name] ?? 'var(--od-line)' }} />
              {p.name}
            </button>
          ))}
        </div>
      </div>

      {/* row 2 — nav tabs + apply/discard */}
      <div className="mt-2 flex min-w-0 items-center gap-2">
        <div className="flex min-w-0 items-center gap-0.5">
          {tools.map((m) => (
            <button
              key={m.id}
              onClick={() => onToolChange(m.id)}
              aria-pressed={tool === m.id}
              title={m.blurb}
              className={`rail-btn !px-2.5 !py-1.5 ${tool === m.id ? 'is-active' : ''}`}
            >
              {m.icon}
              <span className="hidden lg:inline">{m.label}</span>
            </button>
          ))}
          <span className="h-4 w-px bg-od-line" />
          <button
            className={`rail-btn !px-2.5 !py-1.5 ${view === 'map' ? 'is-active' : ''}`}
            onClick={() => onViewChange('map')}
            title="Live city map (home)"
          >
            <span className="hidden lg:inline">MAP</span>
          </button>
          <button
            className={`rail-btn !px-2.5 !py-1.5 ${view === 'venue' ? 'is-active' : ''}`}
            onClick={() => onViewChange('venue')}
            disabled={!canEnterVenue}
            title="Inside the venue (3D twin)"
          >
            <span className="hidden lg:inline">VENUE</span>
          </button>
        </div>

        <span className="hidden min-w-0 truncate text-[9px] uppercase tracking-[0.18em] text-od-muted md:block">
          {blurb}
        </span>

        <span className="flex-1" />

        {(draftPending || cfSimId) && (
          <div className="flex items-center gap-2">
            <span className="hidden text-[9px] uppercase tracking-[0.18em] text-od-muted md:inline">
              where the problem is heading
            </span>
            {draftPending && <span className="chip is-warn !py-0.5">Draft pending</span>}
            {!draftPending && cfSimId && <span className="chip is-warn !py-0.5">What-if forked</span>}
            {draftPending ? (
              <>
                <button className="btn btn-ghost !py-1 text-[10px]" onClick={onClearDraft}>
                  DISCARD
                </button>
                <button className="btn btn-solid !py-1 text-[10px]" onClick={onApplyDraft}>
                  APPLY
                </button>
              </>
            ) : (
              cfSimId && (
                <>
                  <button className="btn btn-ghost !py-1 text-[10px]" onClick={onDiscardCf}>
                    DISCARD
                  </button>
                  <button className="btn btn-solid !py-1 text-[10px]" onClick={onApplyCf}>
                    APPLY TO LIVE
                  </button>
                </>
              )
            )}
          </div>
        )}
      </div>
    </footer>
  );
}