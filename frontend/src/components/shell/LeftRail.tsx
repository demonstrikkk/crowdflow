import { Building2, Box, Radio } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';

interface LeftRailProps {
  onEnterVenue: () => void;
  onBuildTwin: () => void;
}

export default function LeftRail({ onEnterVenue, onBuildTwin }: LeftRailProps) {
  const s = useSimulation();

  const gates = s.venue?.nodes.filter((n) => n.type === 'ENTRY' || n.type === 'EXIT' || n.type === 'EMERGENCY_EXIT').length ?? 0;
  const seats = s.scenario?.crowd_size;
  const cctv = gates;

  return (
    <aside className="flex w-64 shrink-0 flex-col gap-2 overflow-y-auto border-r border-od-line bg-od-panel/60 p-2 scrollbar-thin">
      {/* ── EVENT CONFIG ─────────────────────────────────────────────── */}
      <section className="cmd-panel">
        <div className="cmd-panel-head">
          <span className="sec-label">
            <em>EV</em>Event config
          </span>
          <span className="status-dot is-ok" title="Configuration live" />
        </div>
        <div className="space-y-3 p-2.5">
          <label className="block space-y-1">
            <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-od-muted">Scenario</span>
            <select
              className="field w-full mono-tabular text-[11px]"
              value={s.scenario?.id ?? ''}
              onChange={(e) => void s.selectScenario(e.target.value)}
              aria-label="Select event scenario"
            >
              {s.scenarios.filter((sc) => sc.venue_id === s.venue?.id).map((sc) => (
                <option key={sc.id} value={sc.id}>
                  {sc.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1">
            <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-od-muted">Venue</span>
            <select
              className="field w-full text-[11px]"
              value={s.venue?.id ?? ''}
              onChange={(e) => s.selectVenue(e.target.value)}
              aria-label="Select venue"
            >
              {s.venues.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name.split('—')[0]?.trim() ?? v.name}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-center gap-1.5">
            <button className="btn btn-ghost flex-1" onClick={onEnterVenue} disabled={!s.venue} title="Enter the venue's digital twin">
              <Building2 className="h-3.5 w-3.5" /> ENTER VENUE
            </button>
            <button className="btn btn-ghost flex-1" onClick={onBuildTwin} title="Build a 3D twin from a floor plan">
              <Box className="h-3.5 w-3.5" /> BUILD TWIN
            </button>
          </div>

          <div className="flex items-center gap-2 border-t border-od-line pt-2 text-[9px] uppercase tracking-[0.14em] text-od-muted">
            <Radio className="h-3 w-3 text-od-ok" />
            {s.wsConnected ? 'Simulation feed connected' : 'Simulation feed offline'}
          </div>
        </div>
      </section>

      {/* ── VENUE DETAILS ────────────────────────────────────────────── */}
      <section className="cmd-panel">
        <div className="cmd-panel-head">
          <span className="sec-label">
            <em>VD</em>Venue details
          </span>
        </div>
        <div className="space-y-2.5 p-2.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-od-ink">
              {s.venue?.name.split('—')[0]?.trim() ?? 'No venue'}
            </span>
          </div>
          <div className="text-[9px] leading-snug text-od-muted mono-tabular">
            {s.venue ? `${s.venue.width}×${s.venue.height} m` : 'Select a venue to begin'}
          </div>

          <div className="grid grid-cols-3 gap-1.5 border-t border-od-line pt-2">
            <div className="border border-od-line bg-od-canvas/60 px-1.5 py-1.5 text-center">
              <div className="text-[8px] uppercase tracking-[0.14em] text-od-muted">Seats</div>
              <div className="num mt-0.5 text-[12px] font-bold text-od-ink">{seats?.toLocaleString() ?? '—'}</div>
            </div>
            <div className="border border-od-line bg-od-canvas/60 px-1.5 py-1.5 text-center">
              <div className="text-[8px] uppercase tracking-[0.14em] text-od-muted">Gates</div>
              <div className="num mt-0.5 text-[12px] font-bold text-od-ink">{gates || '—'}</div>
            </div>
            <div className="border border-od-line bg-od-canvas/60 px-1.5 py-1.5 text-center">
              <div className="text-[8px] uppercase tracking-[0.14em] text-od-muted">CCTV</div>
              <div className="num mt-0.5 text-[12px] font-bold text-od-ink">{cctv || '—'}</div>
            </div>
          </div>

          {s.scenario && (
            <div className="flex items-center justify-between text-[9px] uppercase tracking-[0.14em] text-od-muted">
              <span>Arrival</span>
              <span className="num text-od-ink">{s.scenario.arrival_rate_per_minute}/min</span>
            </div>
          )}
        </div>
      </section>
    </aside>
  );
}