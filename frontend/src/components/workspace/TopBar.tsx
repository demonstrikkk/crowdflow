import type { ScenarioModel, SimulationState, VenueModel } from '../../lib/types';
import type { Mode } from '../../lib/selection';
import { Pause, Play } from 'lucide-react';

const MODE_TITLE: Record<Mode, string> = {
  simulate: 'OBSERVE',
  investigate: 'UNDERSTAND',
  intervene: 'ACT',
  compare: 'DECIDE',
};

function WeatherChip({ sim }: { sim: SimulationState }) {
  if (!sim.weather) return null;
  const w = sim.weather;
  return (
    <span
      className={`chip ${w.unsafe_outdoor ? 'is-danger' : w.condition !== 'CLEAR' ? 'is-warn' : ''}`}
      title={`Weather: ${w.condition} · capacity ${Math.round(w.capacity_multiplier * 100)}% · speed ${Math.round(w.speed_multiplier * 100)}%`}
    >
      {w.condition.replace(/_/g, ' ')}
      {w.unsafe_outdoor ? ' ⚠' : ''}
    </span>
  );
}

function IncidentChip({ sim }: { sim: SimulationState }) {
  if (!sim.incident) return null;
  const i = sim.incident;
  const zone = sim.hazard_zones?.[0];
  return (
    <span
      className="chip is-danger"
      title={`${i.type} at ${i.location} · radius ${Math.round(i.radius_m)}m${i.spread_rate_m_min ? ` · spreading ${i.spread_rate_m_min}m/min` : ''}`}
    >
      {i.type} {zone ? `${Math.round(zone.radius_m)}m` : ''}
    </span>
  );
}

export default function TopBar({
  mode,
  venue,
  scenario,
  scenarios,
  onScenario,
  sim,
  wsConnected,
  onPlay,
  onPause,
}: {
  mode: Mode;
  venue: VenueModel | null;
  scenario: ScenarioModel | null;
  scenarios: ScenarioModel[];
  onScenario: (id: string) => void;
  sim: SimulationState | null;
  wsConnected: boolean;
  onPlay: () => void;
  onPause: () => void;
}) {
  const playing = sim?.status === 'RUNNING';
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-od-line bg-od-panel px-3">
      <div className="flex min-w-0 items-baseline gap-3">
        <h2 className="font-display text-[15px] font-bold uppercase tracking-[0.18em] text-od-ink truncate max-w-[200px]" title={venue?.name}>
          {venue?.name ?? '—'}
        </h2>
        <span className="chip" title="Operational state of this workspace">
          <span className={`status-dot ${playing ? 'is-ok' : 'is-scan'}`} />
          {MODE_TITLE[mode]}
        </span>
      </div>

      <span className="h-4 w-px shrink-0 bg-od-line" />

      <div className="flex min-w-0 items-center gap-1.5">
        <span className="sec-label">Event</span>
        <select
          className="field !w-auto max-w-[180px]"
          value={scenario?.id ?? ''}
          onChange={(e) => onScenario(e.target.value)}
          disabled={scenarios.length === 0}
          aria-label="Event scenario"
        >
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      <span className="flex-1" />

      {sim && (
        <div className="hidden items-baseline gap-1.5 sm:flex" title="Simulation clock">
          <span className="sec-label">t=</span>
          <span className="num text-[13px] font-bold text-od-ink">{sim.t_min.toFixed(1)}</span>
          <span className="sec-label">min</span>
        </div>
      )}

      {sim && <WeatherChip sim={sim} />}
      {sim && <IncidentChip sim={sim} />}

      <span
        className={`status-dot ${wsConnected ? 'is-ok' : 'is-scan'}`}
        title={wsConnected ? 'Live feed' : 'No live feed'}
      />

      {sim && (
        <button
          className="btn btn-solid"
          onClick={playing ? onPause : onPlay}
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </button>
      )}
    </header>
  );
}
