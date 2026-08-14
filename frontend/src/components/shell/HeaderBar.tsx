import { Box, Maximize2, Minus, Pause, Play, X } from 'lucide-react';
import { useSimulation } from '../../store/SimulationContext';
import { riskState } from '../../lib/format';
import type { WorldTool } from '../../lib/nav';

/** Remaining minutes to the PEAK phase start; T+ after the peak has begun. */
function tMinus(scenarioMin: number, phases: { name: string; start_minute: number }[]): string | null {
  if (!Number.isFinite(scenarioMin)) return null;
  const peak = phases.find((p) => p.name === 'PEAK');
  if (peak) {
    const delta = peak.start_minute - scenarioMin;
    return delta > 0 ? `T - ${delta.toFixed(1)} MIN` : `T + ${(-delta).toFixed(1)} MIN`;
  }
  return `T ${scenarioMin.toFixed(1)} MIN`;
}

interface HeaderBarProps {
  railsOpen: boolean;
  onToggleRails: () => void;
  twinPanelOpen: boolean;
  onToggleTwinPanel: () => void;
  onCloseEvent: () => void;
  onToggleFullscreen: () => void;
  /** active tool, forwarded so the header can reflect the command context */
  tool: WorldTool;
}

export default function HeaderBar({
  railsOpen,
  onToggleRails,
  twinPanelOpen,
  onToggleTwinPanel,
  onCloseEvent,
  onToggleFullscreen,
  tool,
}: HeaderBarProps) {
  const s = useSimulation();
  const playing = s.sim?.status === 'RUNNING';
  const liveLabel = playing ? 'LIVE' : s.wsConnected ? 'READY' : s.sim ? 'PAUSED' : 'IDLE';
  const liveState = playing ? 'ok' : s.wsConnected ? 'ok' : s.sim ? 'warn' : 'idle';

  const risk = s.displayedSim?.metrics?.risk_level ?? s.sim?.metrics?.risk_level;
  const riskTone = riskState(risk ?? 'NORMAL');
  const riskText = risk === 'CRITICAL' || risk === 'HIGH' ? 'CRITICAL' : risk === 'ELEVATED' ? 'ELEVATED' : 'NOMINAL';

  const peakPct =
    s.displayedSim?.metrics?.max_utilisation != null
      ? Math.round(s.displayedSim.metrics.max_utilisation * 100)
      : s.sim?.metrics?.max_utilisation != null
        ? Math.round(s.sim.metrics.max_utilisation * 100)
        : null;

  const tLabel = tMinus(s.displayedSim?.t_min ?? s.sim?.t_min ?? 0, s.scenario?.event_phases ?? []);

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-od-line bg-od-canvas/80 px-3 backdrop-blur">
      {/* brand */}
      <h1 className="font-display text-[15px] font-extrabold uppercase tracking-[0.26em] text-od-ink whitespace-nowrap">
        Crowd<span className="text-od-ok">Flow</span>
      </h1>

      {/* live status */}
      <span className="chip !cursor-default" title="Simulation feed">
        <span className={`status-dot is-${liveState}`} />
        {liveLabel}
      </span>

      {/* active command context */}
      {tool !== 'live' && (
        <span className="chip is-warn !cursor-default" title="Active command tool">
          {tool.toUpperCase()}
        </span>
      )}

      <span className="h-5 w-px shrink-0 bg-od-line" />

      {/* event selector */}
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="sec-label">EVENT</span>
        <select
          className="field !w-auto max-w-[220px] mono-tabular text-[11px]"
          value={s.scenario?.id ?? ''}
          onChange={(e) => void s.selectScenario(e.target.value)}
          aria-label="Select event scenario"
        >
          {s.scenarios.filter((sc) => sc.venue_id === s.venue?.id).map((sc) => (
            <option key={sc.id} value={sc.id}>
              {sc.name}
              {sc.crowd_size ? ` · ${sc.crowd_size.toLocaleString()}` : ''}
            </option>
          ))}
        </select>
      </div>

      <span className="flex-1" />

      {/* telemetry */}
      {tLabel && (
        <span className="num text-[12px] font-bold text-od-ink whitespace-nowrap" title="Countdown to peak phase">
          {tLabel}
        </span>
      )}

      {s.sim && (
        <>
          <span className={`alert-badge ${riskTone === 'danger' ? '' : riskTone === 'warn' ? 'is-warn' : 'is-ok'}`}>
            <span className="status-dot is-danger" style={{ opacity: riskTone === 'danger' ? 1 : 0.35 }} />
            {riskText}
          </span>
          <span className="hidden items-baseline gap-1.5 md:flex" title="Peak occupancy">
            <span className="sec-label">PEAK</span>
            <span className="num text-[12px] font-bold text-od-ink">{peakPct ?? '—'}%</span>
          </span>
        </>
      )}

      <span className="h-5 w-px shrink-0 bg-od-line" />

      {/* twin badge + build */}
      {s.twinJob?.status === 'COMPLETED' && (
        <span className="chip is-ok !cursor-default" title={`3D twin venue (${s.twinJob.provenance})`}>
          <Box className="h-3 w-3" /> 3D TWIN
        </span>
      )}
      <button
        className="btn btn-ghost"
        onClick={onToggleTwinPanel}
        aria-pressed={twinPanelOpen}
        title="Build a 3D digital twin from a floor plan"
      >
        <Box className="h-3.5 w-3.5" /> BUILD TWIN
      </button>

      <span className="h-5 w-px shrink-0 bg-od-line" />

      {/* transport */}
      {s.sim ? (
        <button
          className="btn btn-solid"
          onClick={() => (playing ? void s.pause() : void s.play())}
          aria-label={playing ? 'Pause simulation' : 'Play simulation'}
          title={playing ? 'Pause simulation' : 'Play simulation'}
        >
          {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
        </button>
      ) : (
        <button className="btn btn-solid" onClick={() => void s.runSimulation()} disabled={!s.scenario}>
          ▶ RUN LIVE SCENARIO
        </button>
      )}

      {/* window controls */}
      <span className="h-5 w-px shrink-0 bg-od-line" />
      <div className="flex items-center gap-1">
        <button
          className="rail-btn rail-icon"
          onClick={onToggleRails}
          aria-pressed={railsOpen}
          title={railsOpen ? 'Collapse side panels' : 'Expand side panels'}
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <button
          className="rail-btn rail-icon"
          onClick={onToggleFullscreen}
          title="Toggle fullscreen"
          aria-label="Toggle fullscreen"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <button className="rail-btn rail-icon" onClick={onCloseEvent} title="Close event session" aria-label="Close event session">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </header>
  );
}