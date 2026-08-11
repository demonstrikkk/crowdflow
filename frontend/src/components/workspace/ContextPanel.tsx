import { useMemo, useState } from 'react';
import type { ElementState, Intervention, SimulationState, VenueModel } from '../../lib/types';
import { riskState } from '../../lib/format';
import type { Mode, Selection } from '../../lib/selection';
import type { DraftState, RedirectDraft } from './InstrumentCanvas';

export interface PanelProps {
  mode: Mode;
  sim: SimulationState | null;
  venue: VenueModel | null;
  selected: Selection | null;
  onSelect: (sel: Selection | null) => void;
  guidedCta: (() => void) | null;
  drafts: DraftState | null;
  onToggleClose: (edgeKey: string) => void;
  onImplementClose: (edgeKey: string) => void;
  onSetRedirect: (r: RedirectDraft | null) => void;
  onImplementRedirect: (r: RedirectDraft) => void;
  onEmergency: (active: boolean) => void;
  onIntervention: (i: Intervention) => void;
  cfSim: SimulationState | null;
  cfError: string | null;
  onDiscardCf: () => void;
  onApplyCf: () => void;
  runCounterfactual: (intervention: Intervention) => Promise<string | null>;
}

function fmt(n: number | undefined | null, digits = 0) {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function RiskBadge({ risk }: { risk: string }) {
  const s = riskState(risk as never);
  return (
    <span className={`chip ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : ''}`}>
      <span className={`status-dot ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`} />
      {risk}
    </span>
  );
}

function ObjectDetail({
  sim,
  venue,
  selected,
}: {
  sim: SimulationState | null;
  venue: VenueModel | null;
  selected: Selection;
}) {
  const node = selected.kind === 'node' ? venue?.nodes.find((n) => n.id === selected.id) : null;
  const edge =
    selected.kind === 'edge' ? venue?.edges.find((e) => `${e.source}→${e.destination}` === selected.id) : null;
  const st: ElementState | undefined =
    sim?.nodes[selected.id] ?? (selected.kind === 'edge' ? sim?.edges[selected.id] : undefined);

  const title =
    selected.kind === 'node'
      ? (node?.id.replace(/_/g, ' ') ?? '?')
      : `${edge?.source.replace(/_/g, ' ')} → ${edge?.destination.replace(/_/g, ' ')}`;
  const type = selected.kind === 'node' ? (node?.type ?? 'NODE') : 'CORRIDOR';

  return (
    <div className="space-y-2.5">
      <div>
        <div className="meta">Selected</div>
        <div className="flex items-center justify-between gap-2">
          <span className="font-display text-[13px] font-bold uppercase tracking-[0.08em] text-od-ink">{title}</span>
          {st && <RiskBadge risk={st.risk} />}
        </div>
        <div className="text-[10px] uppercase tracking-[0.18em] text-od-muted">{type}</div>
      </div>

      {st && (
        <div className="grid grid-cols-3 gap-x-3 gap-y-2 border-t border-od-line pt-2.5">
          <div>
            <div className="meta">People</div>
            <div className="num">{fmt(st.people)}</div>
          </div>
          <div>
            <div className="meta">Queue</div>
            <div className="num">{fmt(st.queue)}</div>
          </div>
          <div>
            <div className="meta">Density</div>
            <div className="num">{fmt(st.density, 2)}</div>
          </div>
          <div>
            <div className="meta">Flow/min</div>
            <div className="num">{fmt(st.flow_per_min)}</div>
          </div>
          <div>
            <div className="meta">Utilisation</div>
            <div className="num">{fmt(st.utilisation * 100, 0)}%</div>
          </div>
          <div>
            <div className="meta">Capacity</div>
            <div className="num">{fmt(st.capacity)}</div>
          </div>
          {st.time_to_critical_min != null && (
            <div className="col-span-3">
              <div className="meta">Time to critical</div>
              <div className="num text-od-warn">{st.time_to_critical_min.toFixed(1)} min</div>
            </div>
          )}
        </div>
      )}

      {selected.kind === 'edge' && edge && (
        <div className="border-t border-od-line pt-2.5">
          <div className="meta">Corridor</div>
          <div className="num">
            {edge.length_m} m × {edge.width_m} m{edge.is_open ? ' · open' : ' · closed'}
          </div>
        </div>
      )}
      {selected.kind === 'node' && node && (
        <div className="border-t border-od-line pt-2.5">
          <div className="meta">Type</div>
          <div className="num">
            {node.type}
            {node.capacity ? ` · capacity ${node.capacity}` : ''}
          </div>
        </div>
      )}
    </div>
  );
}

function SystemReadout({ sim, onSelect }: { sim: SimulationState | null; onSelect: (sel: Selection) => void }) {
  const m = sim?.metrics;
  const top = sim?.bottlenecks[0];
  return (
    <div className="space-y-3">
      <div>
        <div className="meta">System</div>
        <div className="flex items-baseline justify-between">
          <span className="font-display text-[13px] font-bold uppercase tracking-[0.08em] text-od-ink">
            {sim?.phase ?? 'No simulation'}
          </span>
          {m && <RiskBadge risk={m.risk_level} />}
        </div>
      </div>
      {m && (
        <div className="grid grid-cols-3 gap-x-3 gap-y-2 border-t border-od-line pt-2.5">
          <div>
            <div className="meta">In venue</div>
            <div className="num">{fmt(m.in_venue)}</div>
          </div>
          <div>
            <div className="meta">Flow/min</div>
            <div className="num">{fmt(m.flow_per_min)}</div>
          </div>
          <div>
            <div className="meta">Density</div>
            <div className="num">{fmt(m.global_density, 2)}</div>
          </div>
          <div>
            <div className="meta">Queue</div>
            <div className="num">{fmt(m.queue_total)}</div>
          </div>
          <div>
            <div className="meta">Bottlenecks</div>
            <div className="num">{fmt(m.bottleneck_count)}</div>
          </div>
          <div>
            <div className="meta">Avg travel</div>
            <div className="num">{fmt(m.avg_travel_time_min, 1)}m</div>
          </div>
        </div>
      )}

      {top && (
        <button
          className="w-full border border-od-line hover:border-od-warn text-left px-2.5 py-2 cursor-pointer"
          onClick={() => onSelect({ kind: 'edge', id: top.location })}
        >
          <div className="flex items-center justify-between">
            <span className="text-[9px] uppercase tracking-[0.16em] text-od-muted">Top bottleneck</span>
            <RiskBadge risk={top.current_risk} />
          </div>
          <div className="num mt-1">{top.location}</div>
          <div className="text-[10px] text-od-muted mt-1 leading-snug">{top.explanation}</div>
        </button>
      )}

      {sim?.recommended_action && (
        <div className="border border-od-warn bg-od-warn-soft px-2.5 py-2">
          <div className="meta text-od-warn">Recommended action</div>
          <div className="text-[11px] text-od-ink mt-0.5 leading-snug">{sim.recommended_action}</div>
        </div>
      )}
    </div>
  );
}

function BottleneckRegister({
  sim,
  onSelect,
}: {
  sim: SimulationState | null;
  onSelect: (sel: Selection) => void;
}) {
  const sorted = useMemo(() => {
    const list = [...(sim?.bottlenecks ?? [])];
    list.sort((a, b) => b.current_risk.localeCompare(a.current_risk));
    return list;
  }, [sim?.bottlenecks]);
  return (
    <div className="space-y-3">
      <div>
        <div className="meta">Register</div>
        <div className="font-display text-[13px] font-bold uppercase tracking-[0.08em] text-od-ink">
          Bottlenecks · {sorted.length}
        </div>
      </div>
      {sorted.length === 0 && <p className="text-[11px] text-od-muted">No congestion detected at this instant.</p>}
      <div className="space-y-1.5">
        {sorted.map((b) => {
          const s = riskState(b.current_risk as never);
          const sel: Selection = { kind: b.kind, id: b.location };
          return (
            <button
              key={b.id}
              className="w-full border border-od-line hover:border-od-ink text-left px-2.5 py-2 cursor-pointer"
              onClick={() => onSelect(sel)}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-[0.12em] text-od-muted">{b.kind}</span>
                <span className={`status-dot ${s === 'danger' ? 'is-danger' : s === 'warn' ? 'is-warn' : 'is-ok'}`} />
              </div>
              <div className="num mt-0.5 truncate">{b.location}</div>
              <div className="flex justify-between text-[10px] text-od-muted mt-1 mono-tabular">
                <span>util {fmt(b.capacity_utilisation * 100, 0)}%</span>
                <span>queue {fmt(b.queue)}</span>
                <span>density {fmt(b.current_density, 2)}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function InterveneComposer({
  sim,
  venue,
  selected,
  drafts,
  onToggleClose,
  onImplementClose,
  onSetRedirect,
  onImplementRedirect,
  onEmergency,
}: {
  sim: SimulationState | null;
  venue: VenueModel | null;
  selected: Selection | null;
  drafts: DraftState | null;
  onToggleClose: (edgeKey: string) => void;
  onImplementClose: (edgeKey: string) => void;
  onSetRedirect: (r: RedirectDraft | null) => void;
  onImplementRedirect: (r: RedirectDraft) => void;
  onEmergency: (active: boolean) => void;
}) {
  const gates = venue?.nodes.filter((n) => n.type === 'ENTRY') ?? [];
  const closed = new Set(drafts?.closedEdgeIds ?? []);
  const rd = drafts?.redirect ?? null;

  return (
    <div className="space-y-3">
      <div>
        <div className="meta">Composer</div>
        <div className="font-display text-[13px] font-bold uppercase tracking-[0.08em] text-od-ink">Intervention</div>
      </div>

      <div className="border-t border-od-line pt-2.5">
        <div className="meta mb-1.5">Corridors</div>
        {closed.size === 0 && <p className="text-[11px] text-od-muted mb-1.5">Select a corridor on the canvas, then close it here.</p>}
        {[...closed].map((key) => (
          <div key={key} className="flex items-center gap-2 border border-od-danger bg-od-danger-soft px-2 py-1.5 mb-1.5">
            <span className="flex-1 text-[10px] uppercase tracking-[0.1em] text-od-ink truncate">{key}</span>
            <button className="btn btn-danger" onClick={() => onImplementClose(key)}>
              CLOSE
            </button>
          </div>
        ))}
      </div>

      {selected?.kind === 'edge' && (
        <button
          className="btn btn-danger w-full"
          onClick={() => {
            onToggleClose(selected.id);
            onImplementClose(selected.id);
          }}
        >
          CLOSE SELECTED CORRIDOR
        </button>
      )}

      <div className="border-t border-od-line pt-2.5">
        <div className="meta mb-1.5">Redirect a gate</div>
        <div className="flex flex-wrap gap-1">
          {gates.map((g) => (
            <button
              key={g.id}
              className={`chip ${rd?.from === g.id ? 'is-active' : ''}`}
              onClick={() => {
                if (rd?.from === g.id) onSetRedirect(null);
                else {
                  const target = venue?.nodes.find((n) => n.type === 'EXIT');
                  if (target) onSetRedirect({ from: g.id, to: target.id, pct: 20 });
                }
              }}
            >
              {g.id.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        {rd && (
          <div className="mt-2 border border-od-warn bg-od-warn-soft px-2.5 py-2 space-y-2">
            <div className="num truncate">
              {rd.from.replace(/_/g, ' ')} → {rd.to.replace(/_/g, ' ')}
            </div>
            <label className="block">
              <span className="meta">Reroute share</span>
              <input
                type="range"
                min={5}
                max={70}
                step={5}
                value={rd.pct}
                onChange={(e) => onSetRedirect({ ...rd, pct: Number(e.target.value) })}
                className="slider w-full mt-1"
              />
              <span className="num">{rd.pct}%</span>
            </label>
            <div className="flex gap-1.5">
              <button className="btn btn-solid flex-1" onClick={() => onImplementRedirect(rd)}>
                IMPLEMENT
              </button>
              <button className="btn btn-ghost" onClick={() => onSetRedirect(null)}>
                CLEAR
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-od-line pt-2.5">
        <div className="meta mb-1.5">Emergency</div>
        <button
          className="btn btn-danger w-full"
          onClick={() => onEmergency(!(sim?.emergency_active ?? false))}
        >
          {sim?.emergency_active ? 'CANCEL EVACUATION' : 'DECLARE EVACUATION'}
        </button>
      </div>

      {sim && sim.interventions_applied.length > 0 && (
        <div className="border-t border-od-line pt-2.5">
          <div className="meta mb-1">Applied</div>
          {sim.interventions_applied.map((i) => (
            <div key={i.id} className="text-[10px] text-od-muted uppercase tracking-[0.1em] py-0.5 border-b border-od-line last:border-0">
              {i.description}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConditionsComposer({
  sim,
  selected,
  onIntervention,
}: {
  sim: SimulationState | null;
  selected: Selection | null;
  onIntervention: (i: Intervention) => void;
}) {
  const [incidentType, setIncidentType] = useState<'FIRE' | 'SECURITY' | 'STRUCTURAL'>('FIRE');
  const [incidentRadius, setIncidentRadius] = useState(40);
  const [incidentSpread, setIncidentSpread] = useState(0);
  const [weather, setWeather] = useState<'CLEAR' | 'FOG' | 'HEAVY_RAIN' | 'HAIL' | 'HEAT'>('HEAVY_RAIN');
  const [unsafe, setUnsafe] = useState(false);

  const location = selected?.kind === 'node' ? selected.id : sim?.incident?.location ?? 'CONCOURSE_N';

  const startIncident = () => {
    onIntervention({
      id: `inc-${Date.now()}`,
      type: 'ADD_INCIDENT',
      description: `${incidentType} at ${location} (r${incidentRadius}m${incidentSpread ? `, +${incidentSpread}/min` : ''})`,
      parameters: {
        incident: {
          type: incidentType,
          location,
          radius_m: incidentRadius,
          spread_rate_m_min: incidentSpread,
          severity: incidentRadius >= 60 || incidentSpread > 0 ? 'SEVERE' : 'MODERATE',
          blocks_exits: [],
        },
      },
    });
  };

  const applyWeather = () => {
    const condition = weather;
    onIntervention({
      id: `wx-${Date.now()}`,
      type: 'SET_WEATHER',
      description: `${condition.replace(/_/g, ' ')}${unsafe ? ' — outdoor routes closed' : ''}`,
      parameters: {
        weather: {
          condition,
          capacity_multiplier: condition === 'CLEAR' ? 1 : condition === 'FOG' ? 0.75 : 0.55,
          speed_multiplier: condition === 'CLEAR' ? 1 : condition === 'FOG' ? 0.85 : 0.7,
          unsafe_outdoor: unsafe,
          applies_outdoor_only: true,
        },
      },
    });
  };

  const hasConditions = !!(sim?.incident || sim?.weather);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="meta">Conditions</div>
        {hasConditions && <span className="chip is-danger text-[8px]">active</span>}
      </div>

      <div className="border-t border-od-line pt-2.5 space-y-2">
        <div className="meta">Incident</div>
        <div className="flex gap-1">
          {(['FIRE', 'SECURITY', 'STRUCTURAL'] as const).map((t) => (
            <button
              key={t}
              className={`chip ${incidentType === t ? 'is-active' : ''}`}
              onClick={() => setIncidentType(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <label className="block">
          <span className="meta">Location</span>
          <span className="num block">{location.replace(/_/g, ' ')}</span>
          {selected?.kind !== 'node' && <span className="text-[9px] text-od-muted">(select a node on the canvas to aim it)</span>}
        </label>
        <label className="block">
          <span className="meta">Radius {incidentRadius}m</span>
          <input type="range" min={15} max={120} step={5} value={incidentRadius} onChange={(e) => setIncidentRadius(Number(e.target.value))} className="slider w-full mt-1" />
        </label>
        <label className="block">
          <span className="meta">Spread {incidentSpread}m/min</span>
          <input type="range" min={0} max={2} step={0.1} value={incidentSpread} onChange={(e) => setIncidentSpread(Number(e.target.value))} className="slider w-full mt-1" />
        </label>
        <button className="btn btn-danger w-full" onClick={startIncident} disabled={!sim}>
          START {incidentType}
        </button>
      </div>

      <div className="border-t border-od-line pt-2.5 space-y-2">
        <div className="meta">Weather</div>
        <div className="flex flex-wrap gap-1">
          {(['CLEAR', 'FOG', 'HEAVY_RAIN', 'HAIL', 'HEAT'] as const).map((w) => (
            <button
              key={w}
              className={`chip ${weather === w ? 'is-active' : ''}`}
              onClick={() => setWeather(w)}
            >
              {w.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.12em] text-od-muted">
          <input type="checkbox" checked={unsafe} onChange={(e) => setUnsafe(e.target.checked)} />
          Close outdoor routes
        </label>
        <button className="btn btn-solid w-full" onClick={applyWeather} disabled={!sim}>
          APPLY WEATHER
        </button>
      </div>
    </div>
  );
}

function CompareReadout({ sim, cfSim, cfError }: { sim: SimulationState | null; cfSim: SimulationState | null; cfError: string | null }) {
  const base = sim?.metrics;
  const alt = cfSim?.metrics;
  const rows: [string, string | number | null, string | number | null, (a: number, b: number) => boolean][] = [
    ['In venue', base?.in_venue ?? null, alt?.in_venue ?? null, (a, b) => a <= b],
    ['Avg travel', base?.avg_travel_time_min ?? null, alt?.avg_travel_time_min ?? null, (a, b) => a <= b],
    ['Max utilisation', base?.max_utilisation ?? null, alt?.max_utilisation ?? null, (a, b) => a <= b],
    ['Queue total', base?.queue_total ?? null, alt?.queue_total ?? null, (a, b) => a <= b],
    ['Bottlenecks', base?.bottleneck_count ?? null, alt?.bottleneck_count ?? null, (a, b) => a <= b],
  ];
  return (
    <div className="space-y-3">
      <div>
        <div className="meta">Comparison</div>
        <div className="font-display text-[13px] font-bold uppercase tracking-[0.08em] text-od-ink">
          Baseline vs Counterfactual
        </div>
      </div>
      {cfError && <p className="text-[11px] text-od-danger">{cfError}</p>}
      {!cfSim && !cfError && (
        <p className="text-[11px] text-od-muted leading-relaxed">
          Draft an intervention in INTERVENE and run it as a counterfactual to see it here side by side.
        </p>
      )}
      {cfSim && (
        <div className="border-t border-od-line pt-2.5">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 gap-y-1.5 text-[10px] uppercase tracking-[0.12em]">
            <span className="meta">Metric</span>
            <span className="meta text-right">Base</span>
            <span className="meta text-right">Alt</span>
            <span className="meta text-right">Δ</span>
            {rows.map(([label, a, b, better]) => {
              const an = typeof a === 'number' ? a : null;
              const bn = typeof b === 'number' ? b : null;
              const delta = an != null && bn != null ? bn - an : null;
              const good = delta != null && an != null && bn != null ? better(an, bn) : true;
              return (
                <div key={label} className="contents">
                  <span className="text-od-muted pt-0.5">{label}</span>
                  <span className="num text-right">{fmt(an, 1)}</span>
                  <span className="num text-right">{fmt(bn, 1)}</span>
                  <span className={`num text-right ${delta == null ? '' : good ? 'text-od-ok' : 'text-od-danger'}`}>
                    {delta == null ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}`}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="mt-2 pt-2 border-t border-od-line">
            <div className="meta mb-1">Clearance time</div>
            <div className="num">
              {fmt(base?.clearance_time_min, 1)}m → {fmt(alt?.clearance_time_min, 1)}m
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ContextPanel(props: PanelProps) {
  const { mode, sim, selected, onSelect, guidedCta } = props;
  return (
    <aside className="w-80 shrink-0 hidden lg:flex flex-col border-l border-od-line bg-od-panel">
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {mode === 'intervene' ? (
          <div className="space-y-4">
            <InterveneComposer {...props} />
            <div className="border-t border-od-line pt-3">
              <ConditionsComposer sim={sim} selected={selected} onIntervention={props.onIntervention} />
            </div>
          </div>
        ) : mode === 'compare' ? (
          <CompareReadout sim={sim} cfSim={props.cfSim} cfError={props.cfError} />
        ) : mode === 'investigate' ? (
          <div className="space-y-4">
            <BottleneckRegister sim={sim} onSelect={onSelect} />
            {selected && (
              <div className="border-t border-od-line pt-3">
                <ObjectDetail sim={sim} venue={props.venue} selected={selected} />
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {guidedCta && (
              <button
                className="w-full border border-od-warn bg-od-warn-soft text-left px-2.5 py-2.5 cursor-pointer hover:bg-od-warn-soft"
                onClick={guidedCta}
              >
                <div className="meta text-od-warn">Action required</div>
                <div className="text-[12px] font-bold uppercase tracking-[0.06em] text-od-ink mt-0.5">
                  Bottleneck forming — see what we can change
                </div>
              </button>
            )}
            <SystemReadout sim={sim} onSelect={onSelect} />
            {selected && (
              <div className="border-t border-od-line pt-3">
                <ObjectDetail sim={sim} venue={props.venue} selected={selected} />
              </div>
            )}
          </div>
        )}
      </div>
      <div className="border-t border-od-line px-3 py-2 text-[9px] uppercase tracking-[0.18em] text-od-muted">
        {mode} mode
      </div>
    </aside>
  );
}
