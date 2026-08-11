import type { SimulationState } from '../../lib/types';

export default function StatusBar({ sim, wsConnected }: { sim: SimulationState | null; wsConnected: boolean }) {
  const m = sim?.metrics;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-od-line bg-od-panel px-3 py-1.5 text-[9px] uppercase tracking-[0.16em] text-od-muted mono-tabular" role="status">
      <span className="inline-flex items-center gap-1.5">
        <span className={`status-dot ${wsConnected ? 'is-ok' : 'is-scan'}`} />
        {wsConnected ? 'Live' : 'Idle'}
      </span>
      <span>
        <span className="text-od-ink">{sim ? `t=${sim.t_min.toFixed(1)}m` : 't=—'}</span>
      </span>
      <span>phase <span className="text-od-ink">{sim?.phase ?? '—'}</span></span>
      <span>in venue <span className="text-od-ink">{m ? m.in_venue : '—'}</span></span>
      <span>spawned <span className="text-od-ink">{m ? m.total_spawned : '—'}</span></span>
      <span>exited <span className="text-od-ink">{m ? m.total_completed : '—'}</span></span>
      <span>density <span className="text-od-ink">{m ? m.global_density.toFixed(2) : '—'}</span></span>
      <span>flow/min <span className="text-od-ink">{m ? Math.round(m.flow_per_min) : '—'}</span></span>
      <span>queued <span className="text-od-ink">{m ? m.queue_total : '—'}</span></span>
      <span>risk{' '}
        <span className={`${sim?.metrics.risk_level === 'CRITICAL' || sim?.metrics.risk_level === 'HIGH' ? 'text-od-danger' : sim?.metrics.risk_level === 'ELEVATED' ? 'text-od-warn' : 'text-od-ok'}`}>
          {m?.risk_level ?? '—'}
        </span>
      </span>
      {sim?.emergency_active && <span className="text-od-danger">EVACUATION</span>}
      {sim?.incident && (
        <span className="text-od-danger">
          {sim.incident.type} @ {sim.incident.location}
          {sim.hazard_zones?.[0] ? ` · ${Math.round(sim.hazard_zones[0].radius_m)}m` : ''}
        </span>
      )}
      {sim?.weather && (
        <span className={sim.weather.unsafe_outdoor ? 'text-od-danger' : 'text-od-warn'}>
          {sim.weather.condition.replace(/_/g, ' ')}
        </span>
      )}
    </div>
  );
}